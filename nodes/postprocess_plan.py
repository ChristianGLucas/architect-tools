from gen.messages_pb2 import SessionEnvelope
from gen.axiom_context import AxiomContext

from nodes import _runtime as rt

# Platform primitives the planner sometimes scores as "gaps" — they are the
# flow's own mechanics, not missing marketplace capabilities, so a step whose
# only unmatched reason is one of these must NOT drive an honest refusal.
_PRIMITIVE_HINTS = ("join", "compose", "condition", "conditional", "loop", "subflow", "fan-in", "fan-out")


def postprocess_plan(ax: AxiomContext, input: SessionEnvelope) -> SessionEnvelope:
    """No-LLM plan post-processor (the AND-join of carrier state + the planner
    subflow's PlanResult). Filters the planner's known FALSE-gap modes (platform
    primitives scored as gaps) before any refusal is reachable, and marks the
    session plan-ready iff real coverage survives. The planner is advisory
    (~71% strict accuracy), so its picks are treated as evidence, not oracle.
    """
    out = SessionEnvelope()
    out.CopyFrom(input)
    out.phase = "plan_review"

    plan = rt.loads(input.plan_json, default={}) or {}
    # The planner's facade carries the per-step list as steps_json (a JSON
    # string) until nested-facade transcoding lands platform-side; older/typed
    # shapes carry a real steps array. Accept both.
    steps = plan.get("steps") or rt.loads(plan.get("steps_json") or "[]", default=[]) or []
    real_missing = []
    for step in steps:
        if step.get("matched"):
            continue
        why = (step.get("why_unmatched") or step.get("pick_reason") or "").lower()
        if any(h in why for h in _PRIMITIVE_HINTS):
            continue  # false gap — a platform primitive, not a missing node
        real_missing.append(
            {
                "requested_step": step.get("step") or step.get("description", ""),
                "planner_score": step.get("score"),
                "why_unmatched": step.get("why_unmatched") or step.get("pick_reason", ""),
                "nearest_matches": [a.get("package") or a.get("node") for a in (step.get("alternatives") or [])][:3],
            }
        )

    feasible = bool(plan.get("feasible", False)) and not real_missing
    out.plan_ready = feasible
    out.missing_capabilities_json = rt.dumps(real_missing) if real_missing else ""
    out.skeleton_yaml = plan.get("skeleton_yaml", "") or input.skeleton_yaml
    if feasible:
        out.assistant_message = "Plan is feasible from published components. Approve to build."
    else:
        out.assistant_message = "I can't build this from published components (see gaps)."

    ax.log.info("plan post", feasible=feasible, real_gaps=len(real_missing))
    return out
