from gen.messages_pb2 import SessionEnvelope
from gen.axiom_context import AxiomContext

from nodes import _runtime as rt


def agent_turn(ax: AxiomContext, input: SessionEnvelope) -> SessionEnvelope:
    """One bounded conversational/planning step. Decides the next move —
    ``reply`` (talk to the user), ``run_planner`` (plan against the
    marketplace), or ``refuse`` (honestly, only after a planner round). Streams
    its text through ax.progress so the editor sees it as it is produced.
    """
    anthropic, has_anthropic = ax.secrets.get("ANTHROPIC_API_KEY")
    if not has_anthropic:
        out = SessionEnvelope()
        out.CopyFrom(input)
        out.phase = "chat"
        out.assistant_message = "ANTHROPIC_API_KEY is not set for this account."
        out.refusal_reason = "missing ANTHROPIC_API_KEY secret"
        # A missing key is a setup problem, not a plan — route to refuse.
        out.user_action = ""
        _mark_refuse(out)
        return out

    state = _state_dict(input)
    result = rt.run_agent("chat", state, anthropic, progress=_progress(ax))
    decision = result.decision or {}

    out = SessionEnvelope()
    out.CopyFrom(input)
    out.phase = "chat"
    out.assistant_message = result.text
    out.turn_count = input.turn_count + 1
    out.user_action = ""  # consumed; the next resume refills it

    action = decision.get("action", "reply")
    if action == "run_planner":
        out.planner_description = decision.get("description") or input.user_message
    elif action == "refuse":
        out.refusal_reason = decision.get("refusal_reason", "cannot build from published components")
        _mark_refuse(out)
    if decision.get("plan_ready"):
        out.plan_ready = True
        out.phase = "plan_review"

    ax.log.info("agent turn", action=action, turn=int(out.turn_count))
    return out


def _mark_refuse(out: SessionEnvelope) -> None:
    # The flow's conditional edges route on refusal_reason being set.
    out.plan_ready = False


def _state_dict(env: SessionEnvelope) -> dict:
    return {
        "phase": env.phase,
        "user_message": env.user_message,
        "conversation_json": env.conversation_json,
        "current_flow_yaml": env.current_flow_yaml,
        "client_graph_json": env.client_graph_json,
        "plan_json": env.plan_json,
        "turn_count": env.turn_count,
    }


def _progress(ax: AxiomContext):
    emit = getattr(ax, "progress", None)
    if emit is None:
        return None
    return lambda kind, data: emit(kind, data)
