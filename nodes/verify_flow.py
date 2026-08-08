import json

from gen.messages_pb2 import BuildState, VerifyResult
from gen.axiom_context import AxiomContext

from nodes import _runtime as rt


def verify_flow(ax: AxiomContext, input: BuildState) -> VerifyResult:
    """Deterministic verifier (no LLM): validate → compile → preview the risky
    mappings → assemble the SourceGraph the editor applies. A green here is the
    flow's proof-of-work; the assembled graph is what the browser writes to the
    open draft.
    """
    out = VerifyResult()
    out.flow_yaml = input.flow_yaml
    out.conversation_json = input.conversation_json

    report = {"validate": None, "compile": None, "assemble": None}

    axiom_key, _ = ax.secrets.get("AXIOM_API_KEY")
    anthropic, _ = ax.secrets.get("ANTHROPIC_API_KEY")

    if rt.is_fake_key(anthropic):
        # Hermetic path: no CLI/registry. Treat a non-empty flow.yaml as built
        # and emit a minimal SourceGraph so the topology e2e can apply it.
        if input.flow_yaml.strip():
            out.ok = True
            out.updated_graph_json = _fake_source_graph(input.flow_yaml)
            report["validate"] = "ok (fake)"
            report["assemble"] = "ok (fake)"
        else:
            out.ok = False
            out.error = "empty flow.yaml"
        out.report_json = rt.dumps(report)
        return out

    ws = rt.build_workspace(ax.execution_id, axiom_key, login=True, skills=False)
    flow_path = ws.write("flow.yaml", input.flow_yaml)

    validate = rt._run(["axiom", "flow", "validate", flow_path, "--json"], cwd=ws.root, env=ws.env, timeout=60)
    report["validate"] = _tail(validate)
    if validate.returncode != 0:
        out.ok = False
        out.error = "validate failed"
        out.report_json = rt.dumps(report)
        return out

    compile_ = rt._run(["axiom", "flow", "compile", flow_path, "--json"], cwd=ws.root, env=ws.env, timeout=180)
    report["compile"] = _tail(compile_)
    if compile_.returncode != 0:
        out.ok = False
        out.error = "compile failed"
        out.report_json = rt.dumps(report)
        return out

    assemble = rt._run(["axiom", "flow", "assemble", flow_path], cwd=ws.root, env=ws.env, timeout=120)
    report["assemble"] = "ok" if assemble.returncode == 0 else _tail(assemble)
    if assemble.returncode != 0:
        out.ok = False
        out.error = "assemble failed"
        out.report_json = rt.dumps(report)
        return out

    out.ok = True
    out.updated_graph_json = assemble.stdout
    out.report_json = rt.dumps(report)
    ax.log.info("verify ok", bytes=len(out.updated_graph_json))
    return out


def _tail(proc) -> str:
    return (proc.stdout or proc.stderr or "")[-2000:]


def _fake_source_graph(flow_yaml: str) -> str:
    # A minimal but structurally valid SourceGraph the editor can load.
    return json.dumps(
        {
            "name": "christiangeorgelucas/architect-scripted",
            "description": "built by Flow Architect (hermetic)",
            "nodes": [
                {
                    "id": "echo",
                    "type": "axiomNode",
                    "position": {"x": 120, "y": 120},
                    "data": {
                        "nodeUlid": "01SCRIPTEDECHO0000000000000",
                        "packageName": "axiom-official/axiom-durable-test",
                        "packageVersion": "0.3.0",
                        "nodeName": "Echo",
                    },
                }
            ],
            "edges": [],
            "viewport": {"x": 0, "y": 0, "zoom": 1},
        },
        separators=(",", ":"),
    )
