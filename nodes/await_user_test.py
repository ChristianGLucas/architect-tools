from gen.messages_pb2 import SessionEnvelope
from nodes.await_user import await_user
from nodes._testutil import Ctx


def test_echoes_resumed_envelope():
    env = SessionEnvelope(user_message="hi", turn_count=3, user_action="message")
    out = await_user(Ctx(), env)
    assert out.user_message == "hi"
    assert out.turn_count == 3
    assert out.user_action == "message"
