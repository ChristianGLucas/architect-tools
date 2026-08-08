from gen.messages_pb2 import PlanRequest

from nodes.plan import plan


class _Ctx:
    class log:
        @staticmethod
        def info(msg, **attrs):
            pass


def test_returns_feasible_plan_with_one_matched_step():
    out = plan(_Ctx(), PlanRequest(description="anything"))
    assert out.feasible is True
    assert out.skeleton_yaml
    assert len(out.steps) == 1
    s = out.steps[0]
    assert s.matched and s.node == "Echo" and s.package == "axiom-official/axiom-durable-test"
