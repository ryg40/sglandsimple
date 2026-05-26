# Standup Jira Cockpit

Stage 20 introduces a screen-share-first `/standup` workspace around Jira triage and follow-up capture.

## Roles and permissions

- **Session owner / scrum master / product owner**: starts the session, curates context, and approves or rejects proposed actions. Requires the `canApproveStandupActions` capability (maps to the `admin` role / `sg_sec_admin` group).
- **Participant**: contributes chat notes, links, mentions, and Jira context during standup. Any authenticated user may join and chat, but the approval tray is read-only for them.
- **Observer / audit user**: may view the session and contribute notes. Observers cannot approve actions.

Stage 19 capability enforcement is now wired end-to-end:

- **Session join**: the websocket requires a resolved Stage-19 identity unless `AUTH_MODE=disabled`. Unauthenticated clients are closed with a `1008` policy-violation ("authentication required").
- **Snapshot read** (`GET /api/standup/sessions/{id}/snapshot`): requires any authenticated user (401 otherwise).
- **Approve / reject / edit**: gated on `canApproveStandupActions`. Non-approvers receive a `forbidden` websocket error and the tray buttons are disabled with an explanatory tooltip in the UI.
- Presence entries carry a `can_approve` flag so the UI can distinguish approvers from participants.

## Safety policy

- Standup proposals are **dry-run by default**.
- No Jira, Confluence, Archer, ServiceNow, GitHub, Snowflake, or MongoDB production mutation should occur from chat or agent output without explicit human approval.
- `STANDUP_DRY_RUN_ONLY=true` is an extra guardrail: even if connector write flags are enabled, Standup should not perform live external writes. Approving a proposal re-validates any staged Jira edits through Stage-16 `jira_validate_staged` but never calls `jira_apply_staged`; the recorded `approval.applied` is always `false` while this guardrail is on.
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
- The `/standup` aside hosts a live **approval tray** driven by `proposal.created`/`proposal.updated`/`agent.summary` websocket events. Approvers see Approve/Reject buttons; non-approvers see them disabled with a tooltip. A `Summarize` button triggers `agent.summarize` over the live socket. Approvals record `actor`, `decided_at`, `dry_run_only`, `applied`, and the validation `apply_result`.
- The Jira Configuration/tool trace bubble stays collapsed by default and expands to show websocket state, connector health, dry-run/live-write gates, tool traces, and detected cross-service associations.

## Verification

`scripts/smoke_standup_ws.py` runs against the rebuilt stack and asserts: two-client authenticated join/chat, link/mention/Jira-key extraction, dry-run `agent.summarize` proposal persistence, **a non-approver (viewer) approve attempt rejected with `forbidden`**, an **approver (admin) approve flipping the proposal to `approved` with a recorded actor and `applied=false`**, and authenticated snapshot persistence. By default it authenticates with seeded POC users (`avery.stone` viewer, `simone.patel` admin); set `STANDUP_SMOKE_PASSWORD` to match your seed.

## Future work

1. Optional periodic agent summarization (`STANDUP_AGENT_INTERVAL_SECONDS`) instead of on-demand only.
2. Live Jira apply from an approved proposal once `STANDUP_DRY_RUN_ONLY=false` + `JIRA_WRITES_ENABLED=true` are deliberately enabled, reusing the Stage-16 apply gate.
