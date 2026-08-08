from gen.messages_pb2 import BuildState
from gen.axiom_context import AxiomContext

from nodes import _runtime as rt


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
    result = rt.run_agent("build", state, anthropic, workspace=ws, progress=_progress(ax))
    decision = result.decision or {}

    if "flow.yaml" in result.files:
        out.flow_yaml = result.files["flow.yaml"]
    if "worklog.md" in result.files:
        out.work_log_json = result.files["worklog.md"]
    out.step_cursor = input.step_cursor + 1
    out.progress_note = result.text[:500]

    if decision.get("done"):
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
