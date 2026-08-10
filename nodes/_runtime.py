"""Shared runtime for the Flow Architect nodes.

Not a node — a helper module the LLM nodes import. It carries the three things
every agentic node needs and nothing platform-specific belongs in a node
function:

  1. Workspace assembly under /tmp (the only writable path; per-pod, so it is
     rebuilt from the node's input every invocation) — headless `axiom login`,
     the offline flow-authoring skill, and the materialized session files.
  2. A single ``run_agent`` entry point that is EITHER the real Claude Code
     agent (via claude-agent-sdk) OR a deterministic ScriptedAgent, chosen by
     the sentinel-key hermetic switch so CI never makes a live Anthropic call.
  3. Small JSON/text helpers the nodes share.

The sentinel switch (mirrors cmd/bff/docsassistant_fake.go's rationale): when
the tenant's ANTHROPIC_API_KEY *value* begins with ``axiom-test-fake:`` the
suffix names a canned scenario and no network call is made. A CI tenant sets
that secret; production tenants set a real key and are unaffected.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

# ── Environment the injected axiom CLI needs (ADR: the registry-injected binary
# has no baked DeploymentBase, so a node MUST set these before any axiom call).
AXIOM_API_URL = os.environ.get("AXIOM_API_URL", "https://api.axiomide.com/api")
AXIOM_INGRESS_URL = os.environ.get("AXIOM_INGRESS_URL", "https://api.axiomide.com/invocations")

SENTINEL_PREFIX = "axiom-test-fake:"


def is_fake_key(anthropic_key: str) -> bool:
    return anthropic_key.startswith(SENTINEL_PREFIX)


def fake_scenario(anthropic_key: str) -> str:
    return anthropic_key[len(SENTINEL_PREFIX):] if is_fake_key(anthropic_key) else ""


# ──────────────────────────────────────────────────────────────────────────
# Workspace
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class Workspace:
    """A /tmp working directory for one node invocation."""

    root: str
    env: dict

    def path(self, *parts: str) -> str:
        return os.path.join(self.root, *parts)

    def write(self, rel: str, content: str) -> str:
        p = self.path(rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        return p

    def read(self, rel: str) -> str:
        p = self.path(rel)
        if not os.path.exists(p):
            return ""
        with open(p, encoding="utf-8") as f:
            return f.read()


def _run(cmd: list, cwd: str, env: dict, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout, check=False
    )


def build_workspace(execution_id: str, axiom_key: str, *, login: bool = True, skills: bool = True) -> Workspace:
    """Assemble a /tmp workspace: HOME=/tmp is already set by the image, so
    credentials and the skill land on the writable emptyDir. ``login`` and
    ``skills`` are skipped in unit tests (no CLI, no network) via the caller.
    """
    root = os.path.join("/tmp", f"architect-{execution_id}")
    os.makedirs(root, exist_ok=True)
    env = dict(os.environ)
    env.update(
        HOME="/tmp",
        AXIOM_API_URL=AXIOM_API_URL,
        AXIOM_INGRESS_URL=AXIOM_INGRESS_URL,
        # Keep the bundled Claude Code CLI's Node heap bounded for the 1 GiB pod.
        NODE_OPTIONS="--max-old-space-size=512",
    )
    ws = Workspace(root=root, env=env)

    if login and axiom_key:
        login_env = dict(env, AXIOM_API_KEY=axiom_key)
        # AXIOM_API_KEY set ⇒ `axiom login` writes /tmp/.axiom/credentials headlessly.
        _run(["axiom", "login"], cwd=root, env=login_env, timeout=60)

    if skills:
        skills_dir = os.path.join(root, ".claude", "skills")
        os.makedirs(skills_dir, exist_ok=True)
        # Offline: the skill assets are go:embed-ded in the CLI binary.
        _run(["axiom", "skills", "install", "--dir", skills_dir], cwd=root, env=env, timeout=60)

    return ws


# ──────────────────────────────────────────────────────────────────────────
# Agent
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class AgentResult:
    """What a single agent turn returns to a node."""

    text: str = ""
    # Structured decision the node parses (e.g. {"action": "run_planner"}).
    decision: dict = field(default_factory=dict)
    # Files the agent left in the workspace the node should harvest.
    files: dict = field(default_factory=dict)


# progress_cb(kind, data) — the node passes ax.progress so the agent's
# streaming text/steps reach the run-progress surface mid-execution.
ProgressCb = Callable[[str, dict], None]


class ScriptedAgent:
    """Deterministic stand-in for the real Claude Code agent, selected by the
    sentinel key. Scenarios are named by the sentinel suffix; each is a list of
    turn handlers ``(SessionEnvelope-like dict) -> AgentResult`` so a spec can
    drive the exact multi-turn conversation it asserts on. The parsing, state
    threading and file harvest around it are the REAL node code — only the
    model is canned (docsassistant_fake.go rationale).
    """

    def __init__(self, scenario: str) -> None:
        self.scenario = scenario

    def turn(self, kind: str, state: dict, progress: Optional[ProgressCb] = None) -> AgentResult:
        handler = _SCENARIOS.get(self.scenario, _SCENARIOS["default"])
        return handler(kind, state, progress)


def _emit(progress: Optional[ProgressCb], kind: str, data: dict) -> None:
    if progress is not None:
        try:
            progress(kind, data)
        except Exception:
            pass


# ── Canned scenarios. `kind` is "build" | "review". Keep these small and
# deterministic — they exist to exercise the flow's topology + the nodes'
# parse/harvest, not to be smart.


def _scenario_happy(kind: str, state: dict, progress: Optional[ProgressCb]) -> AgentResult:
    if kind == "build":
        _emit(progress, "step_started", {"step": "build"})
        _emit(progress, "step_completed", {"step": "build"})
        return AgentResult(
            text="Built, tested and saved the flow.",
            decision={
                "done": True,
                "status": "built",
                "graph_id": "G-scripted",
                "artifact_id": "A-scripted",
            },
            files={
                "flow.yaml": _MINIMAL_FLOW_YAML,
                "evidence.json": '{"runs":[{"input":"hi","ok":true}]}',
            },
        )
    if kind == "review":
        return AgentResult(
            text="Independently re-ran the oracle; zero critical findings.",
            decision={"approved": True, "summary": "Matches the request and runs clean."},
            files={"graph.json": _MINIMAL_GRAPH_JSON},
        )
    return AgentResult(text="", decision={})


def _scenario_reject_then_approve(kind: str, state: dict, progress: Optional[ProgressCb]) -> AgentResult:
    # Exercises the review→build feedback loop: first review rejects with a
    # CRITICAL finding, the re-entered build round fixes it, second review
    # approves. Also asserts the feedback actually reached the build state.
    if kind == "build":
        fixed = bool(state.get("review_feedback_json"))
        return AgentResult(
            text="Fixed per review feedback." if fixed else "First build attempt.",
            decision={
                "done": True,
                "status": "built",
                "graph_id": "G-fixed" if fixed else "G-draft",
                "artifact_id": "A-fixed" if fixed else "A-draft",
            },
            files={"flow.yaml": _MINIMAL_FLOW_YAML},
        )
    if kind == "review":
        if int(state.get("review_rounds", 0)) <= 1:
            return AgentResult(
                text="Found a critical issue.",
                decision={
                    "approved": False,
                    "findings": [
                        {"severity": "critical", "what": "output field is a false-green", "fix_hint": "assert real value"}
                    ],
                },
            )
        return AgentResult(
            text="Fix confirmed.",
            decision={"approved": True, "summary": "Second pass clean."},
            files={"graph.json": _MINIMAL_GRAPH_JSON},
        )
    return AgentResult(text="", decision={})


def _scenario_always_reject(kind: str, state: dict, progress: Optional[ProgressCb]) -> AgentResult:
    # Drives the reject-budget exhaustion path: review never approves, so the
    # review node must eventually emit final=true / status=failed itself.
    if kind == "build":
        return AgentResult(
            text="Built.",
            decision={"done": True, "status": "built"},
            files={"flow.yaml": _MINIMAL_FLOW_YAML},
        )
    if kind == "review":
        return AgentResult(
            text="Still broken.",
            decision={
                "approved": False,
                "findings": [{"severity": "critical", "what": "does not satisfy the request"}],
            },
        )
    return AgentResult(text="", decision={})


def _scenario_claims_built_no_file(kind: str, state: dict, progress: Optional[ProgressCb]) -> AgentResult:
    # Reproduces a live incident: a build turn reasoned itself into believing
    # it was finished and emitted {"done": true, "status": "built"} without
    # ever writing flow.yaml. build_step must not trust this claim.
    if kind == "build":
        return AgentResult(text="Done.", decision={"done": True, "status": "built"}, files={})
    return AgentResult(text="", decision={})


def _scenario_gave_up(kind: str, state: dict, progress: Optional[ProgressCb]) -> AgentResult:
    if kind == "build":
        return AgentResult(
            text="The marketplace has no node for this capability.",
            decision={
                "done": True,
                "status": "gave_up",
                "gap": {"reason": "no published node covers the requested capability"},
            },
        )
    return AgentResult(text="", decision={})


_MINIMAL_FLOW_YAML = """name: christiangeorgelucas/architect-scripted
version: 0.1.0
nodes:
  - alias: echo
    package: axiom-official/axiom-durable-test@0.3.0
    node: Echo
edges: []
"""

# What `axiom flow assemble` emits for _MINIMAL_FLOW_YAML — the scripted
# reviewer must hand the editor a STRUCTURALLY REAL SourceGraph (nodes carry
# `data` + `position`), because the canvas deserializer throws on anything
# less and the panel's Apply is the surface under test. The nodeUlid is a
# fixed placeholder: fixture pushes mint fresh ULIDs per environment, and the
# editor only renders it (hermetic specs assert topology, not identity).
_MINIMAL_GRAPH_JSON = """{
  "name": "christiangeorgelucas/architect-scripted",
  "version": "0.1.0",
  "description": "",
  "nodes": [
    {
      "id": "echo",
      "data": {
        "nodeUlid": "5YP4VCW5VA0K27R5P6PSCE0KYA",
        "nodeType": "node",
        "packageName": "axiom-official/axiom-durable-test",
        "packageVersion": "0.3.0",
        "nodeName": "Echo",
        "inputMessageName": "Message",
        "outputMessageName": "Message"
      },
      "position": {"x": 0, "y": 0}
    }
  ],
  "edges": [],
  "pipeline_mode": false
}"""

_SCENARIOS: dict[str, Callable[[str, dict, Optional[ProgressCb]], AgentResult]] = {
    "happy": _scenario_happy,
    "reject_then_approve": _scenario_reject_then_approve,
    "always_reject": _scenario_always_reject,
    "gave_up": _scenario_gave_up,
    "claims_built_no_file": _scenario_claims_built_no_file,
    "default": _scenario_happy,
}


def run_agent(
    kind: str,
    state: dict,
    anthropic_key: str,
    *,
    workspace: Optional[Workspace] = None,
    progress: Optional[ProgressCb] = None,
    system_prompt: str = "",
) -> AgentResult:
    """Single agent turn. Hermetic (ScriptedAgent) when the key is a sentinel;
    otherwise the real Claude Code agent over claude-agent-sdk.

    The real path is intentionally thin here — the heavy prompt/policy lives in
    the package's prompts/ dir and the flow-authoring skill in the workspace.
    Kept behind the sentinel so this module imports with no SDK present (unit
    tests never hit it).
    """
    if is_fake_key(anthropic_key):
        return ScriptedAgent(fake_scenario(anthropic_key)).turn(kind, state, progress)
    return _run_real_agent(kind, state, anthropic_key, workspace, progress, system_prompt)


def _run_real_agent(
    kind: str,
    state: dict,
    anthropic_key: str,
    workspace: Optional[Workspace],
    progress: Optional[ProgressCb],
    system_prompt: str,
) -> AgentResult:  # pragma: no cover - exercised only against a live key
    import asyncio

    from claude_agent_sdk import ClaudeAgentOptions, query  # imported lazily

    assert workspace is not None, "real agent requires a workspace"
    prompt = _compose_prompt(kind, state, system_prompt)

    # text_parts lives OUTSIDE _drive so a mid-stream exception (max-turns,
    # transport drop) still leaves everything streamed so far harvestable.
    text_parts: list[str] = []

    async def _drive() -> AgentResult:
        opts = ClaudeAgentOptions(
            cwd=workspace.root,
            # An honest build round (search → inspect → author → validate →
            # preview → compile → run×3 → save) is many tool rounds; a review
            # re-runs the oracle from scratch. The SDK RAISES on max-turns
            # (found live), so keep both generous — the wall-clock guard below
            # is the real budget.
            max_turns=50 if kind == "build" else 30,
            allowed_tools=["Read", "Write", "Grep", "Glob", "Bash"],
            env=dict(workspace.env, ANTHROPIC_API_KEY=anthropic_key),
        )
        async for msg in query(prompt=prompt, options=opts):
            piece = _message_text(msg)
            if piece:
                text_parts.append(piece)
                _emit(progress, "text_delta", {"text": piece})
        return AgentResult(text="".join(text_parts))

    # Wall-clock guard well under the 660 s sidecar ceiling.
    try:
        result = asyncio.run(asyncio.wait_for(_drive(), timeout=float(os.environ.get("ARCHITECT_TURN_TIMEOUT_S", "420"))))
    except asyncio.TimeoutError:
        return AgentResult(text="", decision={"action": "reply", "timeout": True})
    except Exception as exc:  # noqa: BLE001 — degrade, never kill the turn
        # Reached-max-turns (and any other SDK-terminal error) must degrade to
        # a normal reply carrying whatever was already streamed — the user saw
        # that text arrive live; erroring the node retracts it into an opaque
        # "business error" and dead-ends the session.
        partial = "".join(text_parts).strip()
        if not partial:
            raise
        _emit(progress, "text_delta", {"text": "\n\n(turn budget reached — continue the conversation to go on)"})
        result = AgentResult(text=partial)
        result.decision = _parse_decision(partial)
        result.files = _harvest_files(workspace, kind)
        if kind == "build":
            # An unfinished build chunk is not "done" — let the self-loop
            # continue from the harvested state.
            result.decision.setdefault("done", False)
        if kind == "review":
            # An unfinished review must not read as an approval.
            result.decision.setdefault("approved", False)
        result.decision.setdefault("budget_exhausted", True)
        _log_exc = f"{type(exc).__name__}: {exc}"
        print(f"agent turn degraded to partial reply after: {_log_exc}", flush=True)
        return result

    result.decision = _parse_decision(result.text)
    result.files = _harvest_files(workspace, kind)
    return result


def _message_text(msg: Any) -> str:  # pragma: no cover
    # claude-agent-sdk yields typed messages; pull assistant text defensively.
    content = getattr(msg, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(getattr(b, "text", "") for b in content if getattr(b, "text", ""))
    return ""


def _compose_prompt(kind: str, state: dict, system_prompt: str) -> str:  # pragma: no cover
    header = system_prompt or ""
    return f"{header}\n\n[phase={kind}]\n{json.dumps(state)[:100000]}"


DECISION_FENCE = "```axiom-decision"


def _parse_decision(text: str) -> dict:  # pragma: no cover
    # The agent is instructed to end its turn with a decision block under this
    # exact, uniquely-tagged fence — not a generic ```json fence. Both chat and
    # build turns legitimately narrate real CLI/API JSON output inline (e.g.
    # `axiom flow assemble --json`) while they work; a generic tag let the LAST
    # such narrated block shadow the real decision, silently defaulting to
    # {"action": "reply"} (no "done" key) even after a genuinely finished build
    # — which left the build self-loop re-running a completed build from
    # scratch every chunk until it exhausted its iteration budget. Scan
    # backward through every fenced occurrence (not just the last) and accept
    # the first one that parses as a dict carrying a recognized decision key.
    idx = text.rfind(DECISION_FENCE)
    while idx != -1:
        body = text[idx + len(DECISION_FENCE):]
        end = body.find("```")
        candidate = body[:end] if end != -1 else body
        try:
            decision = json.loads(candidate.strip())
        except json.JSONDecodeError:
            decision = None
        if isinstance(decision, dict) and (
            "action" in decision or "done" in decision or "approved" in decision
        ):
            return decision
        idx = text.rfind(DECISION_FENCE, 0, idx)
    return {}


# Which workspace files each phase's node harvests back into structured state.
HARVEST_NAMES = {
    "build": ("flow.yaml", "worklog.md", "evidence.json"),
    "review": ("graph.json", "review.json"),
}


def _harvest_files(workspace: Workspace, kind: str) -> dict:  # pragma: no cover
    out = {}
    for name in HARVEST_NAMES.get(kind, ()):
        content = workspace.read(name)
        if not content:
            content = _find_nested(workspace.root, name)
        if content:
            out[name] = content
    return out


def _find_nested(root: str, name: str) -> str:
    # The build prompt tells the agent to write at the workspace top level, but
    # an agent given free Read/Write/Bash access will sometimes organize its
    # work into a sensibly-named project subdirectory anyway, with a
    # descriptive filename mirroring this repo's own `<name>.flow.yaml`
    # convention (found live: a completely successful build's flow was
    # authored at ./echo/echo-message.flow.yaml, invisible to a strict
    # top-level "flow.yaml" read — so a genuinely finished build looked, to
    # the next self-loop chunk, exactly like no work had happened, forcing a
    # full from-scratch retry every single chunk). Search shallowly (skip
    # dotdirs — credentials/skills live there) for the exact filename, or for
    # `flow.yaml` specifically, any file ending in `.flow.yaml`. The prompt
    # instruction is still the primary contract; this just stops one
    # deviation from being catastrophic.
    suffix = f".{name}" if name == "flow.yaml" else None
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        match = next(
            (f for f in filenames if f == name or (suffix and f.endswith(suffix))), None
        )
        if match:
            try:
                with open(os.path.join(dirpath, match), encoding="utf-8") as f:
                    return f.read()
            except OSError:
                continue
    return ""


# ── JSON helpers ───────────────────────────────────────────────────────────


def loads(s: str, default: Any = None) -> Any:
    if not s:
        return default
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return default


def dumps(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"))
