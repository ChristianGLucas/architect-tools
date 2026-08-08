import json

from gen.messages_pb2 import PlanRequest, PlanResult
from gen.axiom_context import AxiomContext


def plan(ax: AxiomContext, input: PlanRequest) -> PlanResult:
    """Deterministic feasible plan for any description — the devbox e2e
    stand-in for the real flow-planner-fanout subflow."""
    steps = [
        {"matched": True, "package": "axiom-official/axiom-durable-test", "node": "Echo", "score": 0.99},
    ]
    return PlanResult(
        feasible=True,
        skeleton_yaml="name: axiom-official/stub-skeleton\nversion: 0.1.0\nnodes: []\n",
        steps_json=json.dumps(steps),
    )
