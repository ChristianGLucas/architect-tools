from gen.messages_pb2 import SessionEnvelope
from gen.axiom_context import AxiomContext

from nodes import _runtime as rt


def init_session(ax: AxiomContext, input: SessionEnvelope) -> SessionEnvelope:
    """Seed a chat session. Normalizes the facade input into the working
    envelope, logs the CLI in (so later nodes can reach the Axiom API with the
    tenant's own key — ordinary outbound egress, the sanctioned dogfood path),
    and records the starting canvas. The draft is NEVER written by the flow;
    the browser owns that, so client_graph_json rides through unchanged.
    """
    out = SessionEnvelope()
    out.CopyFrom(input)
    out.phase = "chat"
    out.turn_count = 0
    out.plan_ready = False

    axiom_key, ok = ax.secrets.get("AXIOM_API_KEY")
    if ok and not rt.is_fake_key(_anthropic_or_empty(ax)):
        # Warm credentials + the offline authoring skill for the build phase.
        rt.build_workspace(ax.execution_id, axiom_key, login=True, skills=True)

    ax.log.info("architect session started", turn=0, has_graph=bool(input.client_graph_json))
    return out


def _anthropic_or_empty(ax: AxiomContext) -> str:
    v, ok = ax.secrets.get("ANTHROPIC_API_KEY")
    return v if ok else ""
