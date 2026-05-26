# Changelog

## Unreleased

- Fixed Standup chat send rendering so sender-side optimistic messages are acknowledged in place (`sending` → `sent`) instead of duplicating when the websocket broadcast returns.
- Fixed the Compliance Hub Confluence card so disabled live Atlassian MCP gates with seeded sample pages display as dry-run Confluence evidence instead of the misleading generic "Not Connected" summary.
- Documented the distinction between Confluence live health and dry-run overlap-chain sample data in `docs/mcp-in-this-stack.md`.
