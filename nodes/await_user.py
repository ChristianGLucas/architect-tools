from gen.messages_pb2 import SessionEnvelope
from gen.axiom_context import AxiomContext


def await_user(ax: AxiomContext, input: SessionEnvelope) -> SessionEnvelope:
    """The HITL pause point. A pure echo: the flow config marks this node with
    config.hitl, and on resume the user's submitted value BECOMES this node's
    input (the whole SessionEnvelope, echoed back by the client with
    user_action/user_message filled). So the node just forwards what it
    receives — the durable engine handles the pause/resume around it.
    """
    out = SessionEnvelope()
    out.CopyFrom(input)
    return out
