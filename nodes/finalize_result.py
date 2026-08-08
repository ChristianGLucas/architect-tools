from gen.messages_pb2 import ArchitectResult
from gen.axiom_context import AxiomContext


def finalize_result(ax: AxiomContext, input: ArchitectResult) -> ArchitectResult:
    """Terminal shaper. Each terminal path (verify green, builder exhausted,
    agent refuse, user cancel, error funnel) adapts its own message into an
    ArchitectResult on its edge into this node, so finalize receives a single
    ArchitectResult and just enforces the closed status enum + a human summary.
    """
    out = ArchitectResult()
    out.CopyFrom(input)

    status = (input.status or "").lower()
    if status not in ("done", "refused", "failed", "cancelled"):
        # An unset status with a real graph is a success; otherwise a failure.
        status = "done" if input.updated_graph_json else "failed"
    out.status = status

    if not out.summary:
        out.summary = {
            "done": "Flow built and verified.",
            "refused": "I couldn't build this from published components.",
            "failed": "The build did not complete.",
            "cancelled": "Session cancelled.",
        }.get(status, "")

    ax.log.info("architect result", status=status, has_graph=bool(out.updated_graph_json))
    return out
