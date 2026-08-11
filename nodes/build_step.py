import subprocess

from gen.messages_pb2 import BuildState
from gen.axiom_context import AxiomContext

from nodes import _runtime as rt

# Self-imposed round budget. The flow's loop max_iterations is only the
# backstop — the node bounds itself so exhaustion produces an honest gave_up
# instead of a silent loop-cap stall.
MAX_BUILD_ROUNDS = 5

# The build phase's whole policy — the 0.3.0 SPEED bar. The output is a DRAFT
# on the user's canvas: the user sees the wired graph, can run it, and can ask
# again. Speed beats certainty; a 90-second draft that's occasionally wrong is
# worth more than a 15-minute one that's always right.
BUILD_PROMPT = """You are Flow Architect's BUILD agent: turn the user's request into a working Axiom \
flow DRAFT, composing PUBLISHED marketplace components only (never author a new package). You \
have the `axiom` CLI (already logged in) and the axiom-flow-authoring skill in your working \
directory — the skill is authoritative for flow.yaml mechanics.

SPEED IS THE BAR — WALL CLOCK IS THE DELIVERABLE. Your output is a draft the user sees on \
their canvas and can run themselves — not a marketplace publish. The user is WATCHING A TIMER: \
finish this session in about TWO MINUTES. Budget hygiene: ONE marketplace search (two only if \
the first truly misses), inspect ONLY the nodes you will wire, author immediately, and never \
wait more than ~60 seconds on any single command. If the smoke run hits a cold start, retry \
once; if it is still cold, SKIP the smoke run and disclose that in your summary — an untested \
draft beats a slow one. Do NOT: call the planner flow, test-invoke individual nodes, preview \
edge mappings, or run multiple test inputs. If a choice is ambiguous, pick the most obvious \
node and move on. NEVER end a round unfinished when finishing is possible — done=false is for \
genuinely large builds only.

THE WORKFLOW:
1. Resume check: if flow.yaml / worklog.md exist, a prior round left them — continue, never
   restart. If draft.graph.json exists (the user's existing canvas), start from it:
   `axiom flow pull --from-file draft.graph.json -o flow.yaml`.
2. Find parts: `axiom search --type nodes <capability>` and `axiom inspect node <pkg>/<Node>`
   for the exact field names of the nodes you pick. Two or three searches, not a survey.
3. Author flow.yaml at the TOP LEVEL of the working directory. Typed input_facade/output_facade
   with real named fields are MANDATORY; one-line descriptions everywhere.
4. `axiom flow validate` (fix warnings), then `axiom flow compile` (note the artifact id).
5. ONE smoke run: `axiom flow run <artifact-id> -d '<realistic json>'` — confirm the output
   fields carry real values. Cold-start 502 on first invoke is normal — retry once. If a node
   can't be safely live-invoked (keyed/write-path), skip the smoke run and say so in summary.
6. Finish (your LAST steps, exactly once, only when everything above is done):
   `axiom flow save flow.yaml` (note the GRAPH id — save creates a new document every time, so
   never save twice; if a prior round already saved and flow.yaml changed since, save the new
   version and report the NEWEST graph id), then `axiom flow assemble flow.yaml -o graph.json`.
   Do NOT publish — ever.

PROGRESS: as you start each phase, print `STEP: <short phase>` ON ITS OWN LINE (e.g.
`STEP: searching the marketplace`, `STEP: wiring the flow`, `STEP: compiling`,
`STEP: smoke run`, `STEP: saving`). The user watches these live — keep them short and human.

LANDMINES (each has shipped a real bug; the skill has depth on all of them):
- Field casing is snake_case everywhere in CEL/jq paths; confirm real names via `axiom inspect`.
- Guard every edge-adapter scalar pick: `text: '(value.?text).orValue("")'` — a bare pick
  throws on an omitted/empty field at runtime, invisible to validate/compile.
- Guard repeated/list access with `(x.?field).orValue([])`; enums compare as INTEGERS;
  durations are NANOSECONDS (`.getSeconds()` for seconds).
- Nested facade message_names are GLOBAL — prefix them uniquely.
- One forward edge per (source, destination) pair.

Keep worklog.md current (a few lines: done / remaining) so an interrupted round can resume.

If the marketplace genuinely lacks a needed capability, stop and report the gap honestly —
never improvise or fabricate a node reference.

Always end your final message with a decision block under this EXACT fence tag (never ```json
— you will legitimately paste CLI JSON output while narrating; this tag is only for the
decision):
```axiom-decision
{"done": false}
```
(ran out of room; the loop continues next round from your files)
```axiom-decision
{"done": true, "status": "built", "graph_id": "<from flow save>", "artifact_id": "<from compile>", "summary": "<one line: what the flow does + what you verified>"}
```
(built and saved THIS session)
```axiom-decision
{"done": true, "status": "gave_up", "gap": {"reason": "<why>", "missing": ["<capability>"]}}
```
(confirmed capability gap)
"""


def build_step(ax: AxiomContext, input: BuildState) -> BuildState:
    """One bounded build round (self-loop; each round wall-clock-guarded under
    the sidecar call ceiling). Compose-only: published marketplace nodes only.
    On a genuine capability gap it stops with a structured gap, which the
    terminal path turns into an honest refusal rather than an improvised flow.
    """
    out = BuildState()
    out.CopyFrom(input)

    # WARMUP: an empty request is the panel's pre-warm ping for this
    # scale-to-zero pod. Return before touching secrets or the agent so the
    # ping is cheap and needs nothing configured.
    if not input.user_request:
        out.done = True
        out.status = "warmup"
        return out

    out.round = input.round + 1

    anthropic, has_anthropic = ax.secrets.get("ANTHROPIC_API_KEY")
    if not has_anthropic:
        out.done = True
        out.status = "gave_up"
        out.error = "missing ANTHROPIC_API_KEY secret"
        return out

    if input.round >= MAX_BUILD_ROUNDS:
        out.done = True
        out.status = "gave_up"
        out.error = f"build budget exhausted after {int(input.round)} rounds"
        out.gap_json = rt.dumps({"reason": out.error})
        return out

    axiom_key, _ = ax.secrets.get("AXIOM_API_KEY")
    ws = None
    if not rt.is_fake_key(anthropic):
        ws = rt.build_workspace(ax.execution_id, axiom_key, login=True, skills=True)
        if input.flow_yaml:
            ws.write("flow.yaml", input.flow_yaml)
        if input.work_log_json:
            ws.write("worklog.md", input.work_log_json)
        if input.test_evidence_json:
            ws.write("evidence.json", input.test_evidence_json)
        if input.client_graph_json:
            ws.write("draft.graph.json", input.client_graph_json)

    state = {
        "user_request": input.user_request,
        "round": int(out.round),
        "draft_graph_id": input.draft_graph_id,
        "graph_id": input.graph_id,
        "artifact_id": input.artifact_id,
        "has_existing_flow_yaml": bool(input.flow_yaml),
        "model": input.model,
    }
    result = rt.run_agent(
        "build", state, anthropic, workspace=ws, progress=_progress(ax), system_prompt=BUILD_PROMPT
    )
    decision = result.decision or {}

    if "flow.yaml" in result.files:
        out.flow_yaml = result.files["flow.yaml"]
    if "worklog.md" in result.files:
        out.work_log_json = result.files["worklog.md"]
    if "evidence.json" in result.files:
        out.test_evidence_json = result.files["evidence.json"]
    if "graph.json" in result.files:
        out.updated_graph_json = result.files["graph.json"]
    if decision.get("graph_id"):
        out.graph_id = str(decision["graph_id"])
    if decision.get("artifact_id"):
        out.artifact_id = str(decision["artifact_id"])
    if decision.get("summary"):
        out.summary = str(decision["summary"])[:500]
    out.progress_note = result.text[:500]

    if decision.get("done"):
        claimed_built = decision.get("status", "built") == "built" and not decision.get("gap")
        if claimed_built and not out.flow_yaml.strip():
            # Don't trust an unverified "done" claim (found live: a build turn
            # emitted done/built without ever writing flow.yaml). Keep looping
            # — bounded by MAX_BUILD_ROUNDS — so the agent gets a real retry
            # instead of an evidence-free claim reaching the canvas.
            out.progress_note = (
                "(claimed done/built but produced no flow.yaml — retrying) " + out.progress_note
            )[:500]
        else:
            out.done = True
            out.status = decision.get("status", "built")
            if decision.get("gap"):
                out.status = "gave_up"
                out.gap_json = rt.dumps(decision.get("gap"))
            elif not out.updated_graph_json and ws is not None and out.flow_yaml.strip():
                # The agent finished but skipped the assemble step — the graph
                # is what the editor applies, so produce it deterministically
                # (ported from the removed reviewer, where it was proven).
                proc = subprocess.run(
                    ["axiom", "flow", "assemble", "flow.yaml"],
                    cwd=ws.root, env=ws.env, capture_output=True, text=True,
                    timeout=120, check=False,
                )
                if proc.returncode == 0:
                    out.updated_graph_json = proc.stdout.strip()
    ax.log.info("build round", round=int(out.round), done=bool(out.done), status=out.status)
    return out


def _progress(ax: AxiomContext):
    emit = getattr(ax, "progress", None)
    if emit is None:
        return None
    return lambda kind, data: emit(kind, data)
