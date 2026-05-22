# Standup Jira Cockpit

Stage 20 introduces a screen-share-first `/standup` workspace around Jira triage and follow-up capture.

## Roles and permissions

- **Session owner / scrum master / product owner**: starts the session, curates context, and approves or rejects proposed actions.
- **Participant**: contributes chat notes, links, mentions, and Jira context during standup.
- **Observer / audit user**: may view the session and, if policy allows, contribute notes. Observers cannot approve actions.
- **Admin fallback**: until Stage 19 capability enforcement is wired end-to-end, `sg_sec_admin` / admin users are treated as the approval authority.

Future backend enforcement should map approval to `canApproveStandupActions` and keep route/session access aligned with Stage 19 RBAC.

## Safety policy

- Standup proposals are **dry-run by default**.
- No Jira, Confluence, Archer, ServiceNow, GitHub, Snowflake, or MongoDB production mutation should occur from chat or agent output without explicit human approval.
- `STANDUP_DRY_RUN_ONLY=true` is an extra guardrail: even if connector write flags are enabled, Standup should not perform live external writes.
- Jira live writes still require `JIRA_WRITES_ENABLED=true` and the existing Stage 16 validation/apply gates.
- The initial `/standup` shell disables Jira apply from the embedded grid until Standup approval/RBAC is implemented; users can stage and validate only.

## Current slice

- `/standup` provides an Explorer-dominant layout using the existing Jira editable grid.
- FastAPI websocket chat persists session snapshots, messages, agent runs, and proposals in the web-owned JSON store.
- Chat identity is wired to the Stage-19 auth context when available: message bubbles and presence use the logged-in display name, and persisted messages keep `author_email` for cross-service references. Auth-disabled or unresolved sessions fall back to the browser/legacy author behavior.
- `standup_link_context` and `standup_summarize` MCP helpers remain dry-run/side-effect-free.
- `standup_summarize` passes deterministic story-template context to the planner: acceptance-criteria format, default standup labels, priority/story-point guidance, selected epic/workflow context, and relevant Docs Wiki/Confluence links. Returned `new_jira_work` proposals are normalized to keep these fields in the dry-run payload.
- Websocket `agent.summarize` persists dry-run standup proposals. Existing-Jira edit proposals with concrete `issue_key`/`changes` are staged and validated through the Stage-16 Jira staging tools, but the Standup path never calls live apply.
- The Jira Configuration/tool trace bubble stays collapsed by default and expands to show websocket state, connector health, dry-run/live-write gates, tool traces, and detected cross-service associations.

## Future work

1. Add the full audited approval/edit/reject tray and enforce scrum-master/product-owner capability checks end-to-end.
2. Re-enable apply from Standup only after approval/RBAC gates are active.
3. Run the full rebuilt-stack websocket + agent + dry-run smoke and screen-share UI review.
