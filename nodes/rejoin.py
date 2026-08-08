from gen.messages_pb2 import SessionEnvelope
from gen.axiom_context import AxiomContext


def rejoin(ax: AxiomContext, input: SessionEnvelope) -> SessionEnvelope:
    """Loop-head funnel. A pure echo whose flow config carries the XOR join over
    its two conditional in-edges (a plain chat turn from await_user, or a
    post-plan envelope from plan_post). Exactly one arrives per iteration; the
    single back-edge rejoin→agent_turn carries the loop. Keeping this an echo
    lets agent_turn have one forward in-edge + one back-edge (no join on the
    loop head).
    """
    out = SessionEnvelope()
    out.CopyFrom(input)
    return out
