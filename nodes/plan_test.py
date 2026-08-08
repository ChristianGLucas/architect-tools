from gen.messages_pb2 import PlanRequest

from nodes.plan import plan


class _Ctx:
    class log:
        @staticmethod
        def info(msg, **attrs):
            pass


def test_returns_feasible_plan():
    out = plan(_Ctx(), PlanRequest(description="anything"))
    assert out.feasible is True
    assert out.skeleton_yaml
    assert "Echo" in out.steps_json
