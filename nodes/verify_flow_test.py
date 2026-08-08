import json
from gen.messages_pb2 import BuildState
from nodes.verify_flow import verify_flow
from nodes._testutil import Ctx


def test_scripted_emits_source_graph():
    out = verify_flow(Ctx("happy"), BuildState(flow_yaml="name: x\nversion: 0.1.0\nnodes: []\n"))
    assert out.ok is True
    assert json.loads(out.updated_graph_json)["nodes"]


def test_empty_yaml_fails():
    out = verify_flow(Ctx("happy"), BuildState(flow_yaml=""))
    assert out.ok is False
    assert out.error
