from gen.messages_pb2 import SessionEnvelope
from gen.axiom_context import AxiomContext


def carrier(ax: AxiomContext, input: SessionEnvelope) -> SessionEnvelope:
    """Carrier-funnel echo (flow-authoring skill pattern): the planner subflow's
    facade input is fixed, so the session state cannot ride through it. carrier
    echoes the whole envelope on a second edge straight to plan_post, while the
    edge into the planner subflow adapts only planner_description → the
    planner's `description` facade field. plan_post then AND-joins the two.
    """
    out = SessionEnvelope()
    out.CopyFrom(input)
    return out
