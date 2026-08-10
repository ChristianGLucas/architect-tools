from gen.messages_pb2 import BuildState
from gen.axiom_context import AxiomContext

from nodes import _runtime as rt

# The build turn's policy. This self-loops up to 20 chunks; without an explicit
# decision contract the agent had nothing telling it to signal completion, so
# a fully successful build (validated, compiled, run live, saved) never set
# `done`, and the next chunk redid the entire build from scratch — repeating
# until the loop exhausted its budget and error-routed to a refusal, even
# though every individual chunk had actually succeeded.
BUILD_PROMPT = """You are the Flow Architect's build phase: turn an approved plan into a compiled, verified Axiom flow — compose-only, from PUBLISHED marketplace components only (never author a new package).

This is ONE bounded chunk of a self-looping build (up to 20 chunks). Before doing anything, check the incoming state (flow_yaml, work_log_json, step_cursor) for work already done in a prior chunk — resume from there, do NOT redo completed work from scratch.

Only report done=true once you have, for real, in this session:
- validated the flow (axiom flow validate)
- compiled it (axiom flow compile)
- previewed any risky edge mappings
- run it live (or against mocks the plan calls for) and checked output field by field
- saved it as an editable draft graph (axiom flow save)
Do NOT publish — that is a separate, irreversible action the user takes later.

If you hit a genuine capability gap the marketplace cannot cover, stop and report it rather than improvising or fabricating a node.

Always end your final message with a fenced decision block using this EXACT tag (not ```json — you will legitimately show real CLI/API JSON output inline while you work; use this dedicated tag only for the decision, never for anything else):
```axiom-decision
{"done": false}
```
(this chunk made progress but the build isn't finished — the loop calls you again with your updated state)
```axiom-decision
{"done": true, "status": "built"}
```
(fully built, verified, and saved this session)
```axiom-decision
{"done": true, "status": "gave_up", "gap": {"reason": "<why>"}}
```
(genuine capability gap)
"""


def build_step(ax: AxiomContext, input: BuildState) -> BuildState:
    """One bounded build chunk (self-loop; each iteration wall-clock-guarded far
    under the 660 s sidecar ceiling). Compose-only: the agent may only use nodes
    from the verified plan + marketplace search — never author packages. On a
    genuine mid-build capability gap it stops with a gap, which finalize turns
    into an honest refusal rather than an improvised flow.
    """
    out = BuildState()
    out.CopyFrom(input)

    anthropic, has_anthropic = ax.secrets.get("ANTHROPIC_API_KEY")
    if not has_anthropic:
        out.done = True
        out.status = "gave_up"
        out.error = "missing ANTHROPIC_API_KEY secret"
        return out

    axiom_key, _ = ax.secrets.get("AXIOM_API_KEY")
    ws = None
    if not rt.is_fake_key(anthropic):
        ws = rt.build_workspace(ax.execution_id, axiom_key, login=True, skills=True)
        if input.flow_yaml:
            ws.write("flow.yaml", input.flow_yaml)
        if input.work_log_json:
            ws.write("worklog.md", input.work_log_json)

    state = {
        "flow_yaml": input.flow_yaml,
        "verified_plan_json": input.verified_plan_json,
        "skeleton_yaml": input.skeleton_yaml,
        "work_log_json": input.work_log_json,
        "step_cursor": input.step_cursor,
    }
    result = rt.run_agent(
        "build", state, anthropic, workspace=ws, progress=_progress(ax), system_prompt=BUILD_PROMPT
    )
    decision = result.decision or {}

    if "flow.yaml" in result.files:
        out.flow_yaml = result.files["flow.yaml"]
    if "worklog.md" in result.files:
        out.work_log_json = result.files["worklog.md"]
    out.step_cursor = input.step_cursor + 1
    out.progress_note = result.text[:500]

    if decision.get("done"):
        claimed_built = decision.get("status", "built") == "built" and not decision.get("gap")
        if claimed_built and not out.flow_yaml.strip():
            # Don't trust an unverified "done" claim. Found live: a build turn
            # reasoned about the task, decided it was finished, and emitted
            # {"done": true, "status": "built"} without ever writing a
            # flow.yaml — verify_flow's own validate step correctly caught the
            # empty file, but the flow's verify->finalize edge routed it to
            # "Flow built and verified." anyway (fixed separately in the flow
            # graph). Keep looping — bounded by the self-loop's
            # max_iterations — so the agent gets a real further chance instead
            # of a claim with no evidence ever reaching verify at all.
            out.progress_note = (
                "(claimed done/built but produced no flow.yaml — retrying) " + out.progress_note
            )[:500]
        else:
            out.done = True
            out.status = decision.get("status", "built")
            if decision.get("gap"):
                out.status = "gave_up"
                out.gap_json = rt.dumps(decision.get("gap"))
    ax.log.info("build step", cursor=int(out.step_cursor), done=bool(out.done), status=out.status)
    return out


def _progress(ax: AxiomContext):
    emit = getattr(ax, "progress", None)
    if emit is None:
        return None
    return lambda kind, data: emit(kind, data)
