from gen.messages_pb2 import SessionEnvelope
from nodes.agent_turn import agent_turn
from nodes._testutil import Ctx


def test_first_turn_requests_planner():
    out = agent_turn(Ctx("happy"), SessionEnvelope(user_message="build an RSS digest", turn_count=0))
    assert out.planner_description == "build an RSS digest"
    assert out.turn_count == 1
    assert out.user_action == ""


def test_missing_anthropic_key_refuses_not_crashes():
    out = agent_turn(Ctx(secrets={"AXIOM_API_KEY": "x"}), SessionEnvelope(user_message="x"))
    assert "ANTHROPIC_API_KEY" in out.refusal_reason
    assert out.plan_ready is False
