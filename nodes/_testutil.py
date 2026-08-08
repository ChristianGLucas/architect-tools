"""Shared AxiomContext double for the Flow Architect node tests. Not a node —
a helper the per-node *_test.py files import. The sentinel ANTHROPIC_API_KEY
routes run_agent through the ScriptedAgent so no network/CLI is touched while
the REAL parse/state/harvest code runs."""


class _Log:
    def debug(self, *a, **k):
        pass

    info = warn = error = debug


class _Secrets:
    def __init__(self, values):
        self._v = values

    def get(self, name):
        if name in self._v:
            return self._v[name], True
        return "", False


class Ctx:
    """Minimal AxiomContext double. Deliberately has NO `progress` attribute so
    the nodes' getattr guard is exercised. Pass secrets=None to omit a key."""

    def __init__(self, scenario="happy", secrets=None):
        self.log = _Log()
        self.secrets = _Secrets(
            secrets
            if secrets is not None
            else {
                "ANTHROPIC_API_KEY": f"axiom-test-fake:{scenario}",
                "AXIOM_API_KEY": "axiom-test-fake:key",
            }
        )
        self.execution_id = "exec-test"
