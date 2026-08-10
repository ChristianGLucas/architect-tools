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
    # 0.3.0: the build itself delivers the editor graph + a one-line summary
    # (no reviewer to produce them anymore).
    assert '"nodes"' in out.updated_graph_json
    assert out.summary != ""
    assert out.round == 1


def test_empty_request_is_a_cheap_warmup_ping():
    # The panel pre-warms the scale-to-zero pod by invoking with an empty
    # request. Must return immediately WITHOUT touching secrets — an
    # ungranted tenant's ping should not fail on secret delivery.
    out = build_step(Ctx(secrets={}), BuildState())
    assert out.done is True
    assert out.status == "warmup"
    assert out.round == 0
    assert out.error == ""


def test_missing_key_gives_up_cleanly():
    out = build_step(Ctx(secrets={"AXIOM_API_KEY": "x"}), BuildState(user_request="x"))
    assert out.done is True
    assert out.status == "gave_up"


def test_round_budget_exhaustion_gives_up_honestly():
    # The node bounds itself: exhaustion must produce a structured gave_up
    # (routable to an honest refusal), never a silent loop-cap stall.
    out = build_step(Ctx("happy"), BuildState(user_request="x", round=MAX_BUILD_ROUNDS))
    assert out.done is True
    assert out.status == "gave_up"
    assert "budget exhausted" in out.error
    assert out.gap_json != ""


def test_claimed_built_without_flow_yaml_keeps_looping():
    # Live incident: a build turn emitted {"done": true, "status": "built"}
    # without ever writing flow.yaml. build_step must not trust the claim —
    # the self-loop should get another real chance instead of handing the
    # canvas an empty flow.
    out = build_step(Ctx("claims_built_no_file"), BuildState(user_request="x"))
    assert out.done is False
    assert out.status == ""
    assert out.flow_yaml == ""
    assert "retrying" in out.progress_note


def test_second_round_completes_after_a_hollow_claim():
    # Round 2 of the same scenario delivers — pins that the self-loop carries
    # enough state for the retry to finish (round counter drives the fixture).
    out = build_step(Ctx("claims_built_no_file"), BuildState(user_request="x", round=1))
    assert out.done is True
    assert out.status == "built"
    assert out.graph_id == "G-round2"
    assert '"nodes"' in out.updated_graph_json


def test_capability_gap_becomes_gave_up_with_detail():
    out = build_step(Ctx("gave_up"), BuildState(user_request="do the impossible"))
    assert out.done is True
    assert out.status == "gave_up"
    assert "no published node" in out.gap_json
