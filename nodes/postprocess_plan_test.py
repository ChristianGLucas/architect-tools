import json
from gen.messages_pb2 import SessionEnvelope
from nodes.postprocess_plan import postprocess_plan
from nodes._testutil import Ctx


def test_filters_platform_primitive_false_gaps():
    plan = {"feasible": True, "skeleton_yaml": "name: x\n", "steps": [
        {"matched": True, "package": "a/b", "node": "N"},
        {"matched": False, "why_unmatched": "needs a join across two sources"},
    ]}
    out = postprocess_plan(Ctx(), SessionEnvelope(plan_json=json.dumps(plan)))
    assert out.plan_ready is True
    assert out.missing_capabilities_json == ""


def test_reports_real_gap_and_blocks_plan_ready():
    plan = {"feasible": True, "steps": [
        {"matched": False, "step": "transcribe audio", "why_unmatched": "no speech-to-text node published", "score": 0.2},
    ]}
    out = postprocess_plan(Ctx(), SessionEnvelope(plan_json=json.dumps(plan)))
    assert out.plan_ready is False
    assert json.loads(out.missing_capabilities_json)[0]["requested_step"] == "transcribe audio"
