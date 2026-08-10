from gen.messages_pb2 import BuildState
from nodes.build_step import MAX_BUILD_ROUNDS, build_step
from nodes._testutil import Ctx


def test_scripted_one_shot_builds():
    out = build_step(Ctx("happy"), BuildState(user_request="echo my message"))
    assert out.done is True
    assert out.status == "built"
    assert out.flow_yaml.strip() != ""
    assert out.graph_id == "G-scripted"
    assert out.artifact_id == "A-scripted"
    assert out.test_evidence_json != ""
    assert out.round == 1


def test_missing_key_gives_up_cleanly():
    out = build_step(Ctx(secrets={"AXIOM_API_KEY": "x"}), BuildState())
    assert out.done is True
    assert out.status == "gave_up"


def test_round_budget_exhaustion_gives_up_honestly():
    # The node bounds itself: exhaustion must produce a structured gave_up
    # (routable to an honest refusal), never a silent loop-cap stall.
    out = build_step(Ctx("happy"), BuildState(round=MAX_BUILD_ROUNDS))
    assert out.done is True
    assert out.status == "gave_up"
    assert "budget exhausted" in out.error
    assert out.gap_json != ""


def test_claimed_built_without_flow_yaml_keeps_looping():
    # Live incident: a build turn emitted {"done": true, "status": "built"}
    # without ever writing flow.yaml. build_step must not trust the claim —
    # the self-loop should get another real chance instead of handing review
    # an empty flow.
    out = build_step(Ctx("claims_built_no_file"), BuildState())
    assert out.done is False
    assert out.status == ""
    assert out.flow_yaml == ""
    assert "retrying" in out.progress_note


def test_capability_gap_becomes_gave_up_with_detail():
    out = build_step(Ctx("gave_up"), BuildState(user_request="do the impossible"))
    assert out.done is True
    assert out.status == "gave_up"
    assert "no published node" in out.gap_json


def test_review_feedback_reaches_the_agent_and_is_consumed():
    # The reject_then_approve scenario's build turn reports G-fixed only when
    # it actually saw feedback in its state — pinning that the loop-back
    # feedback is delivered, and that it is cleared after being consumed
    # (never re-applied stale on a later round).
    fed = build_step(
        Ctx("reject_then_approve"),
        BuildState(user_request="x", review_feedback_json='[{"severity":"critical"}]', round=1, review_rounds=1),
    )
    assert fed.graph_id == "G-fixed"
    assert fed.review_feedback_json == ""

    fresh = build_step(Ctx("reject_then_approve"), BuildState(user_request="x"))
    assert fresh.graph_id == "G-draft"
