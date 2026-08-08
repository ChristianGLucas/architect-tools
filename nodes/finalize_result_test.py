from gen.messages_pb2 import ArchitectResult
from nodes.finalize_result import finalize_result
from nodes._testutil import Ctx


def test_defaults_status_from_presence_of_graph():
    assert finalize_result(Ctx(), ArchitectResult(updated_graph_json="{}")).status == "done"
    assert finalize_result(Ctx(), ArchitectResult()).status == "failed"


def test_preserves_explicit_refused():
    out = finalize_result(Ctx(), ArchitectResult(status="refused", missing_capabilities_json="[]"))
    assert out.status == "refused"
    assert out.summary
