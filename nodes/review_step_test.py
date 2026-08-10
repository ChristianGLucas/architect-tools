import json

from gen.messages_pb2 import BuildState
from nodes.review_step import MAX_REVIEW_ROUNDS, review_step
from nodes._testutil import Ctx


def _built_state(**kw):
    return BuildState(
        user_request="echo my message",
        flow_yaml="name: x/y\nversion: 0.1.0\nnodes: []\n",
        graph_id="G-1",
        artifact_id="A-1",
        test_evidence_json='{"runs":[]}',
        done=True,
        status="built",
        **kw,
    )


def test_approval_is_final_with_assembled_graph():
    out = review_step(Ctx("happy"), _built_state())
    assert out.final is True
    assert out.approved is True
    assert out.status == "done"
    assert json.loads(out.updated_graph_json)["nodes"]
    assert out.review_rounds == 1
    # Carried state survives for the (untaken) loop-back edge.
    assert out.flow_yaml != ""
    assert out.user_request == "echo my message"


def test_rejection_loops_back_with_structured_findings():
    out = review_step(Ctx("reject_then_approve"), _built_state())
    assert out.final is False
    assert out.approved is False
    findings = json.loads(out.findings_json)
    assert findings[0]["severity"] == "critical"
    # Loop-back carry: build must be able to resume from this verdict.
    assert out.flow_yaml != ""
    assert out.graph_id == "G-1"


def test_reject_budget_exhaustion_ends_the_session_failed():
    out = review_step(Ctx("always_reject"), _built_state(review_rounds=MAX_REVIEW_ROUNDS - 1))
    assert out.final is True
    assert out.approved is False
    assert out.status == "failed"
    assert out.error != ""


def test_missing_key_fails_closed():
    out = review_step(Ctx(secrets={"AXIOM_API_KEY": "x"}), _built_state())
    assert out.final is True
    assert out.status == "failed"
    assert out.approved is False


def test_approval_without_graph_json_downgrades_to_rejection():
    # An "approved" verdict the editor can't apply is useless — the node must
    # convert it into a precise rejection with a finding, not ship an empty
    # done. Register a scenario that approves without writing graph.json.
    from nodes import _runtime as rt

    def _scenario(kind, state, progress):
        if kind == "review":
            return rt.AgentResult(text="lgtm", decision={"approved": True})
        return rt.AgentResult(text="", decision={})

    rt._SCENARIOS["approve_no_files"] = _scenario
    try:
        out = review_step(Ctx("approve_no_files"), _built_state())
    finally:
        del rt._SCENARIOS["approve_no_files"]
    assert out.final is False
    assert out.approved is False
    assert "no graph JSON" in out.findings_json
