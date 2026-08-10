from gen.messages_pb2 import BuildState
from nodes.build_step import build_step
from nodes._testutil import Ctx


def test_scripted_one_shot_builds():
    out = build_step(Ctx("happy"), BuildState(skeleton_yaml="name: christiangeorgelucas/x\nversion: 0.1.0\nnodes: []\n", step_cursor=0))
    assert out.done is True
    assert out.status == "built"
    assert out.flow_yaml.strip() != ""
    assert out.step_cursor == 1


def test_missing_key_gives_up_cleanly():
    out = build_step(Ctx(secrets={"AXIOM_API_KEY": "x"}), BuildState())
    assert out.done is True
    assert out.status == "gave_up"


def test_claimed_built_without_flow_yaml_keeps_looping():
    # Live incident: a build turn emitted {"done": true, "status": "built"}
    # without ever writing flow.yaml. build_step must not trust the claim —
    # the flow's self-loop should get another real chance instead of handing
    # verify_flow an empty file that silently reports "Flow built and verified."
    out = build_step(Ctx("claims_built_no_file"), BuildState(step_cursor=0))
    assert out.done is False
    assert out.status == ""
    assert out.flow_yaml == ""
    assert "retrying" in out.progress_note
