from gen.messages_pb2 import ErrInfo
from nodes.err_shape import err_shape
from nodes._testutil import Ctx


def test_maps_node_error_to_failed():
    out = err_shape(Ctx(), ErrInfo(reason="sidecar reset"))
    assert out.status == "failed"
    assert out.error == "sidecar reset"
