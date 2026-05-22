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
- The chat and proposal panels are local frontend placeholders until websocket persistence lands.
- `standup_link_context` and `standup_summarize` MCP helpers are dry-run/side-effect-free.

## Future work

1. Persist `standup_sessions`, `standup_messages`, `standup_agent_runs`, and `standup_proposals`.
2. Add FastAPI websocket fanout with reconnect snapshots.
3. Wire the frontend chat to the backend and MCP standup helpers.
4. Add audited approval/edit/reject flows.
5. Re-enable apply from Standup only after approval/RBAC gates are active.
