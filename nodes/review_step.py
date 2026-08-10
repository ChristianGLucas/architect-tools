import subprocess

from gen.messages_pb2 import BuildState, ReviewVerdict
from gen.axiom_context import AxiomContext

from nodes import _runtime as rt

# After this many completed review passes without an approval, the review node
# ends the session itself (final=true, status=failed) instead of bouncing the
# build forever. The flow's loop max_iterations is only the backstop.
MAX_REVIEW_ROUNDS = 3

# The independent reviewer's policy — the flow-seeding playbook's Phase 5
# checklist. Builder≠reviewer is load-bearing: this is a FRESH agent that
# re-verifies from scratch and treats the builder's evidence as claims.
REVIEW_PROMPT = """You are Flow Architect's REVIEW agent: an INDEPENDENT reviewer of a flow another \
agent just built. You have the `axiom` CLI (already logged in). The working directory has \
flow.yaml (the built flow), request.md (what the user asked for), and evidence.json (the \
builder's OWN account of what it ran — treat as unverified claims, not facts).

RE-RUN THE ORACLE FROM SCRATCH with your own inputs. Do not rubber-stamp the evidence.
1. Does flow.yaml actually satisfy request.md — the user's real ask, not a drifted variant?
2. `axiom flow validate` — zero warnings. `axiom flow compile` — get your own artifact id
   (or use the builder's if compile is deterministic-identical).
3. `axiom flow run <artifact-id> -d '<json>'` with inputs YOU choose: a happy path, a sparse
   input (optionals absent, lists empty), and a bad/malformed input. Cold-start 502 → retry.
4. FALSE-GREEN HUNT: cross-check every output field against the underlying node schemas
   (`axiom inspect node <pkg>/<Node>`) — a wrong-cased CEL/jq path runs green and silently
   returns defaults. Assert every meaningful output field carries a REAL, non-default value.
5. GATE CONSISTENCY on the degenerate inputs: ok:true must never co-occur with a non-empty
   error; empty/malformed input must behave exactly as the facade descriptions promise.
6. Honesty: facade + flow descriptions must describe what it actually does; typed facades
   (never opaque {json}-in / values-out); no baked secret values anywhere.

Severity: CRITICAL = wrong/dishonest output, false-green, gate inconsistency, doesn't satisfy
the request, missing/untyped facade, secret leakage. Everything else is minor — note it but
do not reject for it. Zero CRITICAL findings = approve.

IF YOU APPROVE, produce the editor graph before ending your turn:
`axiom flow assemble flow.yaml -o graph.json`
Optionally write review.json with your full run record (inputs, outputs, checks).

Always end your final message with a decision block under this EXACT fence tag (never
```json):
```axiom-decision
{"approved": true, "summary": "<one-line verdict>"}
```
```axiom-decision
{"approved": false, "findings": [{"severity": "critical", "what": "<the defect>", "fix_hint": "<how to fix>"}]}
```
"""


def review_step(ax: AxiomContext, input: BuildState) -> ReviewVerdict:
    """Independent review of a build that claims done+built. Approve → final
    verdict with the assembled editor graph. Reject → findings loop back into
    the next build round, bounded by MAX_REVIEW_ROUNDS.
    """
    out = ReviewVerdict()
    # Carry the session state for the loop-back edge.
    out.flow_yaml = input.flow_yaml
    out.graph_id = input.graph_id
    out.artifact_id = input.artifact_id
    out.test_evidence_json = input.test_evidence_json
    out.work_log_json = input.work_log_json
    out.user_request = input.user_request
    out.client_graph_json = input.client_graph_json
    out.draft_graph_id = input.draft_graph_id
    out.model = input.model
    out.round = input.round
    out.review_rounds = input.review_rounds + 1

    anthropic, has_anthropic = ax.secrets.get("ANTHROPIC_API_KEY")
    if not has_anthropic:
        out.final = True
        out.status = "failed"
        out.error = "missing ANTHROPIC_API_KEY secret"
        return out

    axiom_key, _ = ax.secrets.get("AXIOM_API_KEY")
    ws = None
    if not rt.is_fake_key(anthropic):
        # A DISTINCT workspace from the build's (same pod would reuse the
        # execution-scoped dir and leak the builder's scratch state into the
        # "independent" review).
        ws = rt.build_workspace(f"{ax.execution_id}-review", axiom_key, login=True, skills=True)
        ws.write("flow.yaml", input.flow_yaml)
        ws.write("request.md", input.user_request)
        ws.write("evidence.json", input.test_evidence_json or "{}")

    state = {
        "user_request": input.user_request,
        "graph_id": input.graph_id,
        "artifact_id": input.artifact_id,
        "review_rounds": int(out.review_rounds),
        "model": input.model,
    }
    result = rt.run_agent(
        "review", state, anthropic, workspace=ws, progress=_progress(ax), system_prompt=REVIEW_PROMPT
    )
    decision = result.decision or {}
    out.report_json = rt.dumps({"text": result.text[:4000], "decision": decision})

    if decision.get("approved"):
        graph_json = result.files.get("graph.json", "")
        if not graph_json and ws is not None:
            # The reviewer approved but skipped the assemble step — do it
            # deterministically; approval without an applicable graph is
            # useless to the editor.
            proc = subprocess.run(
                ["axiom", "flow", "assemble", "flow.yaml"],
                cwd=ws.root, env=ws.env, capture_output=True, text=True, timeout=120, check=False,
            )
            if proc.returncode == 0:
                graph_json = proc.stdout.strip()
        if graph_json:
            out.final = True
            out.approved = True
            out.status = "done"
            out.summary = str(decision.get("summary", "")) or "Flow built, independently reviewed, and verified."
            out.updated_graph_json = graph_json
            ax.log.info("review approved", rounds=int(out.review_rounds))
            return out
        # Approval with no graph — treat as a rejection with a precise finding
        # rather than shipping an unusable "done".
        decision = {
            "approved": False,
            "findings": [{
                "severity": "critical",
                "what": "review approved but `axiom flow assemble` produced no graph JSON",
                "fix_hint": "ensure flow.yaml assembles cleanly",
            }],
        }

    findings = decision.get("findings") or [
        {"severity": "critical", "what": "review rejected without structured findings"}
    ]
    out.findings_json = rt.dumps(findings)

    if out.review_rounds >= MAX_REVIEW_ROUNDS:
        out.final = True
        out.status = "failed"
        out.summary = f"Review rejected the build {int(out.review_rounds)} times; giving up."
        out.error = rt.dumps(findings)
        ax.log.info("review budget exhausted", rounds=int(out.review_rounds))
    else:
        ax.log.info("review rejected", rounds=int(out.review_rounds))
    return out


def _progress(ax: AxiomContext):
    emit = getattr(ax, "progress", None)
    if emit is None:
        return None
    return lambda kind, data: emit(kind, data)
