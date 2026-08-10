from nodes._runtime import Workspace, _harvest_files, _parse_decision


def test_parses_trailing_decision_block():
    text = 'Built and verified.\n```axiom-decision\n{"done": true, "status": "built"}\n```'
    assert _parse_decision(text) == {"done": True, "status": "built"}


def test_narrated_cli_json_after_decision_does_not_shadow_it():
    # The agent legitimately pastes real CLI/API JSON output while narrating
    # its work (e.g. showing `axiom flow assemble --json`) AFTER the decision
    # block. A naive "last ```json fence wins" parser would grab that
    # narration instead of the real decision — the exact bug that let a fully
    # successful build loop forever because `done` never came back true.
    text = (
        "Saved.\n"
        '```axiom-decision\n{"done": true, "status": "built"}\n```\n'
        "For reference, here is the assembled graph:\n"
        '```json\n{"name": "my-flow", "nodes": []}\n```\n'
    )
    assert _parse_decision(text) == {"done": True, "status": "built"}


def test_narrated_cli_json_before_decision_does_not_shadow_it():
    text = (
        "Let me check the envelope shape:\n"
        '```json\n{"result": {"output": {"ok": true}}}\n```\n'
        "Now the real decision:\n"
        '```axiom-decision\n{"done": false}\n```'
    )
    assert _parse_decision(text) == {"done": False}


def test_no_decision_block_defaults_to_reply():
    assert _parse_decision("just some prose, no decision block") == {"action": "reply"}


def test_malformed_decision_block_falls_back_to_earlier_valid_one():
    text = (
        '```axiom-decision\n{"done": true, "status": "built"}\n```\n'
        "oops, then a broken one:\n"
        "```axiom-decision\nnot valid json\n```"
    )
    assert _parse_decision(text) == {"done": True, "status": "built"}


def test_harvest_finds_flow_yaml_in_a_project_subdirectory(tmp_path):
    # Found live: a genuinely finished build wrote its flow into a sensibly
    # named project subdirectory (./echo/echo-message.flow.yaml) instead of
    # the workspace top level. A strict top-level-only read saw an empty
    # flow.yaml, so build_step's own "don't trust an unverified done claim"
    # guard rejected 13 consecutive fully-successful builds in a row and
    # forced a from-scratch retry every time.
    ws = Workspace(root=str(tmp_path), env={})
    nested = tmp_path / "echo"
    nested.mkdir()
    (nested / "echo-message.flow.yaml").write_text("name: my/echo\nversion: 0.1.0\n")

    out = _harvest_files(ws, "build")

    assert out["flow.yaml"] == "name: my/echo\nversion: 0.1.0\n"


def test_harvest_prefers_top_level_flow_yaml_over_a_nested_one(tmp_path):
    ws = Workspace(root=str(tmp_path), env={})
    (tmp_path / "flow.yaml").write_text("top-level")
    nested = tmp_path / "echo"
    nested.mkdir()
    (nested / "other.flow.yaml").write_text("nested")

    out = _harvest_files(ws, "build")

    assert out["flow.yaml"] == "top-level"


def test_harvest_ignores_dotdirs(tmp_path):
    ws = Workspace(root=str(tmp_path), env={})
    dotdir = tmp_path / ".claude" / "skills"
    dotdir.mkdir(parents=True)
    (dotdir / "flow.yaml").write_text("should not be harvested")

    out = _harvest_files(ws, "build")

    assert "flow.yaml" not in out
