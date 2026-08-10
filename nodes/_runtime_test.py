from nodes._runtime import _parse_decision


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
