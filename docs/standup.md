# Standup Jira Cockpit

Stage 20 introduces a screen-share-first `/standup` workspace around Jira triage and follow-up capture.

## Roles and permissions

- **Session owner / scrum master / product owner**: starts the session, curates context, and approves or rejects proposed actions. Requires the `canApproveStandupActions` capability (maps to the `admin` role / `sg_sec_admin` group).
- **Participant**: contributes chat notes, links, mentions, and Jira context during standup. Any authenticated user may join and chat, but the approval tray is read-only for them.
- **Observer / audit user**: may view the session and contribute notes. Observers cannot approve actions.

Stage 19 capability enforcement is now wired end-to-end:

- **Session join**: the websocket requires a resolved Stage-19 identity unless `AUTH_MODE=disabled`. Unauthenticated clients are closed with a `1008` policy-violation ("authentication required").
- **Snapshot read** (`GET /api/standup/sessions/{id}/snapshot`): requires any authenticated user (401 otherwise).
- **Approve / reject / edit / submit**: gated on `canApproveStandupActions` or the `STANDUP_APPROVER_EMAILS` auth-system allowlist. The default named production approver is `simone.patel@lanGarland.com` (case-insensitive). Non-approvers receive a `forbidden` websocket error and the approval controls are disabled with an explanatory tooltip in the UI.
- Presence entries carry a `can_approve` flag so the UI can distinguish approvers from participants.

## Safety policy

- Standup proposals are **dry-run by default**.
- No Jira, Confluence, Archer, ServiceNow, GitHub, Snowflake, or MongoDB production mutation should occur from chat or agent output without explicit human approval.
- `STANDUP_DRY_RUN_ONLY=true` is an extra guardrail: even if connector write flags are enabled, Standup should not perform live external writes. S25 Submit re-stages and re-validates Jira edits, but calls `jira_apply_staged` only when `STANDUP_DRY_RUN_ONLY=false`, `WORKFLOW_WRITES_ENABLED=true`, and `JIRA_WRITES_ENABLED=true` are all deliberately enabled.
- Jira live writes still require `JIRA_WRITES_ENABLED=true` and the existing Stage 16 validation/apply gates.
- The embedded grid keeps `allowApply={false}` in Standup; create/edit follow-ups flow through the dry-run proposal tray, not direct grid apply.

## Current slice

- `/standup` provides an Explorer-dominant layout using the existing Jira editable grid.
- FastAPI websocket chat persists session snapshots, messages, agent runs, and proposals in the web-owned JSON store.
- Chat identity is wired to the Stage-19 auth context when available: message bubbles and presence use the logged-in display name, and persisted messages keep `author_email` for cross-service references. Auth-disabled or unresolved sessions fall back to the browser/legacy author behavior.
- Sender-side chat delivery is a single dynamic bubble: the optimistic local message shows `sending`, then the server echo is correlated by `client_message_id`, replaces the local bubble, and shows `sent` only to the sender. Other participants see the accepted message once without delivery status.
- `standup_link_context` and `standup_summarize` MCP helpers remain dry-run/side-effect-free.
- `standup_summarize` passes deterministic story-template context to the planner: acceptance-criteria format, default standup labels, priority/story-point guidance, selected epic/workflow context, and relevant Docs Wiki/Confluence links. Returned `new_jira_work` proposals are normalized to keep these fields in the dry-run payload.
- Websocket `agent.summarize` persists dry-run standup proposals. Existing-Jira edit proposals with concrete `issue_key`/`changes` are staged and validated through the Stage-16 Jira staging tools, but the Standup path never calls live apply.
- The `/standup` layout (Stage 27) keeps the **chat panel in the right-hand column** and stacks the working cards in the main left section in this order: **Jira Explorer → Epics + Templates (two-up grid) → Approvals viewport → Jira Configuration / tool trace**. The chat header has a **Widen/Collapse** toggle: widening triples the chat column from the `23rem` rail to `69rem` (the main section keeps the remaining space) for easier screen-share reading; collapsing returns it to the `23rem` rail. Chat send, presence, and Summarize behave identically in both states.
- **Epics** and **Templates** render as a two-up grid directly under Jira Explorer. **Epics** is a collapsed-by-default reference card that expands into a read-only active-epic list sourced from `/api/standup/epics` (the `epics` collection via MCP). Rows show key/title/program area/status/priority, tags, regulation refs, database/platform combos, ticket refs, finding links, and Jira deep links. Selecting a row sets local selected-epic context as the seam for future agent resolution.
- **Templates** sits beside Epics. It remains collapsed by default and expands into a read-only per-epic customized-fields table plus a prompt-library dropdown/Markdown viewport sourced from the backend-owned `standup_templates` MCP tool. This shared store is the same source Stage-21 Deep Agent context packs read, avoiding duplicate Jira/Confluence generation prompts.
- The **Approvals viewport** is a full-width live card below the Epics/Templates grid, driven by `proposal.created`/`proposal.updated`/`agent.summary` websocket events. It opens with an inline **How to use this** guide (capture chat → Summarize → review/edit payload → Save → Submit/Reject) so first-time approvers understand the dry-run-by-default flow. Approvers can edit each staged JSON payload, **Save** edits without applying, **Submit** through the gated production path, or Reject. Non-approvers see the controls disabled with a tooltip and a read-only notice. A `Summarize` button triggers `agent.summarize` over the live socket. Approvals record `actor`, `decided_at`, original payload, edited payload, validation result, dry-run/live mode, and the apply result.
- The **Jira Configuration / tool trace** card is the **last** item in the main section; its show/hide toggle expands its content (websocket state, connector health, dry-run/live-write gates, tool traces, detected cross-service associations) without reflowing the surrounding layout. Collapsed by default so the grid stays dominant.

## Verification

`scripts/smoke_standup_ws.py` runs against the rebuilt stack and asserts: two-client authenticated join/chat, link/mention/Jira-key extraction, dry-run `agent.summarize` proposal persistence, **a non-approver (viewer) approve attempt rejected with `forbidden`**, an **approver (admin) approve flipping the proposal to `approved` with a recorded actor and `applied=false`**, and authenticated snapshot persistence. By default it authenticates with seeded POC users (`avery.stone` viewer, `simone.patel` admin); set `STANDUP_SMOKE_PASSWORD` to match your seed.

## Future work

1. Optional periodic agent summarization (`STANDUP_AGENT_INTERVAL_SECONDS`) instead of on-demand only.
2. Live Jira apply from an approved proposal once `STANDUP_DRY_RUN_ONLY=false` + `JIRA_WRITES_ENABLED=true` are deliberately enabled, reusing the Stage-16 apply gate.
3. Stage-24 editability follow-up: the Epics fields table and prompt library are intentionally read-only today. The implementation leaves two seams for a future audited editor: (a) epic table values render through a typed field-spec + `FieldCell` component so inline editors can replace the presentational cells, and (b) prompt bodies come from `mcp/standup_templates.py::list_templates()` so a future `standup_templates_upsert` MCP tool can move the store to Mongo, audit updates, and feed both the UI and Deep Agent context packs without rewriting the Standup page.
