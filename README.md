# christiangeorgelucas/architect-tools

The agentic node package behind **Flow Architect** — the in-editor AI flow author.

One durable HITL chat session = one `flow-architect` flow execution. These nodes
plan (via the published `flow-planner-fanout` subflow), converse with the user
through a HITL loop, build the flow with Claude Code + the `axiom` CLI, verify it
deterministically, and emit the SourceGraph the editor applies. **Compose-only:**
if the marketplace lacks the needed nodes, it refuses honestly with the gap
detail — it never authors packages or improvises.

Secrets (BYO, tenant-scoped, console-set): `ANTHROPIC_API_KEY`, `AXIOM_API_KEY`.

Hermetic CI: an `ANTHROPIC_API_KEY` whose value begins `axiom-test-fake:<scenario>`
routes the LLM nodes through a deterministic ScriptedAgent — no network call.
