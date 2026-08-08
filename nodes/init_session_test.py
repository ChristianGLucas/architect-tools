from gen.messages_pb2 import SessionEnvelope
from nodes.init_session import init_session
from nodes._testutil import Ctx


def test_init_seeds_chat_and_preserves_client_graph():
    env = SessionEnvelope(user_message="build an RSS digest", client_graph_json='{"nodes":[]}')
    out = init_session(Ctx(), env)
    assert out.phase == "chat"
    assert out.turn_count == 0
    assert out.plan_ready is False
    assert out.client_graph_json == '{"nodes":[]}'  # flow never writes the draft
