from gen.messages_pb2 import SessionEnvelope
from nodes.rejoin import rejoin
from nodes._testutil import Ctx


def test_echoes():
    out = rejoin(Ctx(), SessionEnvelope(turn_count=3, plan_ready=True))
    assert out.turn_count == 3
    assert out.plan_ready is True
