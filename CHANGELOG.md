# Changelog

## Unreleased

### Added
- Optional `sandbox` Deep Agent runtime container (Stage 21), gated behind the `sandbox` compose profile and off by default. Start with `docker compose --profile sandbox up -d`; it runs as a non-root user and shares the `./sandbox` mount with the MCP service. New env vars: `DEEP_AGENT_RUNTIME_MODE`, `DEEP_AGENT_ARTIFACT_DIR`, `DEEP_AGENT_DRY_RUN_ONLY`.

### Changed
- Upgraded the MCP service to the LangChain 1.x line (`deepagents` 0.6.3, `langchain-core` 1.4, `langgraph` 1.2, `langchain-openai` 1.2, `openai` 2.x, `langgraph-checkpoint-mongodb` 0.4) in preparation for the Stage-21 Deep Agent platform. The Mongo checkpointer now uses the unified `MongoDBSaver`; existing `ask_data`, `deep_agent`, docs-agent HITL, agent tool-loop, and workflow smokes pass unchanged.

- Fixed Standup chat send rendering so sender-side optimistic messages are acknowledged in place (`sending` → `sent`) instead of duplicating when the websocket broadcast returns.
- Fixed the Compliance Hub Confluence card so disabled live Atlassian MCP gates with seeded sample pages display as dry-run Confluence evidence instead of the misleading generic "Not Connected" summary.
- Documented the distinction between Confluence live health and dry-run overlap-chain sample data in `docs/mcp-in-this-stack.md`.
