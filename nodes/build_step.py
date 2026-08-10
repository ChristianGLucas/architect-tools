from gen.messages_pb2 import BuildState
from gen.axiom_context import AxiomContext

from nodes import _runtime as rt

# Self-imposed round budget. The flow's loop max_iterations is only the
# backstop — the node bounds itself so exhaustion produces an honest gave_up
# instead of a silent loop-cap stall.
MAX_BUILD_ROUNDS = 8

# The build phase's whole policy. Condensed from the battle-tested
# axiom-flow-authoring / flow-seeding playbook (the same workflow that seeded
# the marketplace's published flows) — the agent IS the workflow; the flow
# graph around it only provides durability, chunking and independent review.
BUILD_PROMPT = """You are Flow Architect's BUILD agent: turn the user's request into a working, \
tested Axiom flow, composing PUBLISHED marketplace components only (never author a new package). \
You have the `axiom` CLI (already logged in) and the axiom-flow-authoring skill installed in \
your working directory — the skill is authoritative for flow.yaml mechanics.

MATCH YOUR EFFORT TO THE TASK. A simple request (one or two obvious nodes) should be planned, \
built, tested and saved in THIS single session — do not spread trivial work across rounds. \
Only genuinely large builds should end a round unfinished (done=false) to continue next round.

THE WORKFLOW (skip steps that are obviously unnecessary for a trivial task):
1. Resume check: if flow.yaml / worklog.md / feedback.md exist in the working directory, a
   prior round or a reviewer left them — build on that work, never restart from scratch.
2. If draft.graph.json exists (the user's existing canvas), convert it to a starting flow.yaml:
   `axiom flow pull --from-file draft.graph.json -o flow.yaml`.
3. Optionally get a plan skeleton: `axiom flow run 01KZMNJ1ZDQ62KRYQTGVGS8NR7 -d
   '{"description":"<one-line task>"}' --timeout 300 --json` (the published planner flow).
   It is ADVISORY (~71% accurate): confirm every pick with `axiom search --type nodes`,
   `axiom info <pkg>`, `axiom inspect node <pkg>/<Node>` before wiring; substitute freely.
4. Author flow.yaml at the TOP LEVEL of the working directory (exactly `flow.yaml` — files in
   subdirectories are invisible to the platform). Typed input_facade/output_facade with real
   named fields are MANDATORY; every facade field and message needs a description.
5. Verify, in order: `axiom flow validate` (zero warnings), `axiom flow preview` each nontrivial
   edge mapping, `axiom flow compile` (note the artifact id), then LIVE-RUN the compiled
   artifact with `axiom flow run <artifact-id> -d '<json>'` on THREE inputs — happy-path,
   sparse (optionals absent / lists empty), and bad/malformed (must yield a clean typed
   negative, not a traceback). Assert every meaningful output field carries a REAL value.
   For a node you cannot safely live-invoke (keyed/write-path), use `axiom flow mock add` and
   disclose the mock in your evidence. Cold-start 502 on first invoke is normal — retry once.
6. Save the draft: `axiom flow save flow.yaml` (note the GRAPH id). Do NOT publish — ever.

LANDMINES (each has shipped a real bug; the skill has depth on all of them):
- Field casing is snake_case everywhere in CEL/jq paths; confirm real names via `axiom inspect`.
- Guard every edge-adapter scalar pick: `text: '(value.?text).orValue("")'` — a bare pick
  throws on an omitted/empty field at runtime, invisible to validate/compile.
- Guard repeated/list access with `(x.?field).orValue([])`; enums compare as INTEGERS;
  durations are NANOSECONDS (`.getSeconds()` for seconds).
- Nested facade message_names are GLOBAL — prefix them uniquely.
- One forward edge per (source, destination) pair.
- Gate consistency: ok:true and a non-empty error must never co-occur; degenerate inputs must
  behave exactly as your facade descriptions promise.

RECORD AS YOU GO (top-level files, harvested as this round's output):
- worklog.md — steps done / remaining (your resume ledger).
- evidence.json — {"graph_id": "...", "artifact_id": "...", "runs": [{"input": ..., "output":
  ..., "ok": true}]} — the honest record of what you actually ran. The independent reviewer
  re-verifies from scratch; fabricated evidence WILL be caught and bounced back.

If feedback.md exists, a reviewer REJECTED the previous result — address every critical
finding before claiming done again.

If the marketplace genuinely lacks a needed capability, stop and report the gap honestly —
never improvise or fabricate a node reference.

Always end your final message with a decision block under this EXACT fence tag (never ```json
— you will legitimately paste CLI JSON output while narrating; this tag is only for the
decision):
```axiom-decision
{"done": false}
```
(made progress; the loop continues next round from your files)
```axiom-decision
{"done": true, "status": "built", "graph_id": "<from flow save>", "artifact_id": "<from compile>"}
```
(fully built, verified and saved THIS session — goes to independent review)
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
    out.round = input.round + 1
    out.review_feedback_json = ""  # consumed this round; never re-applied stale

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
        if input.review_feedback_json:
            ws.write("feedback.md", input.review_feedback_json)

    state = {
        "user_request": input.user_request,
        "round": int(out.round),
        "review_feedback_json": input.review_feedback_json,
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
    if decision.get("graph_id"):
        out.graph_id = str(decision["graph_id"])
    if decision.get("artifact_id"):
        out.artifact_id = str(decision["artifact_id"])
    out.progress_note = result.text[:500]

    if decision.get("done"):
        claimed_built = decision.get("status", "built") == "built" and not decision.get("gap")
        if claimed_built and not out.flow_yaml.strip():
            # Don't trust an unverified "done" claim (found live: a build turn
            # emitted done/built without ever writing flow.yaml). Keep looping
            # — bounded by MAX_BUILD_ROUNDS — so the agent gets a real retry
            # instead of an evidence-free claim reaching review.
            out.progress_note = (
                "(claimed done/built but produced no flow.yaml — retrying) " + out.progress_note
            )[:500]
        else:
            out.done = True
            out.status = decision.get("status", "built")
            if decision.get("gap"):
                out.status = "gave_up"
                out.gap_json = rt.dumps(decision.get("gap"))
    ax.log.info("build round", round=int(out.round), done=bool(out.done), status=out.status)
    return out


def _progress(ax: AxiomContext):
    emit = getattr(ax, "progress", None)
    if emit is None:
        return None
    return lambda kind, data: emit(kind, data)
