from gen.messages_pb2 import ErrInfo, ArchitectResult
from gen.axiom_context import AxiomContext


def err_shape(ax: AxiomContext, input: ErrInfo) -> ArchitectResult:
    """on_error funnel. The flow routes a terminally-failing node's NodeError
    here (edge adapter {reason: message}); this shapes it into a failed
    ArchitectResult so the single finalize path stays typed. Kept separate from
    finalize because a (from,to) pair cannot carry both a normal and an
    on_error edge.
    """
    out = ArchitectResult()
    out.status = "failed"
    out.error = input.reason
    out.summary = "The build did not complete."
    ax.log.error("architect node failed", reason=input.reason)
    return out
