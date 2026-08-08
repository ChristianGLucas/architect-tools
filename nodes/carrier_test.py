from gen.messages_pb2 import SessionEnvelope
from nodes.carrier import carrier
from nodes._testutil import Ctx


def test_echoes_state_for_the_funnel():
    out = carrier(Ctx(), SessionEnvelope(planner_description="d", client_graph_json="{}"))
    assert out.planner_description == "d"
    assert out.client_graph_json == "{}"
