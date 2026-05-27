# Progress

## Status
**Stages 0–2, 4, 6–20, 22, 23, 24, 25, 31, and 32 COMPLETE. Stage 3 transport/expose COMPLETE locally (manual external-client smoke pending). Stage 14 COMPLETE incl. docs-agent LangGraph HITL apply gate. Stage 18 architecture v2 COMPLETE. Stage 21 IN PROGRESS. Stage 26 chat runtime visibility S26.chat-runtime.1 COMPLETE. Stage 5 SHELVED.**
Work branch: `main`; latest observed HEAD before current work: `625878c` (`feat(S21): context packs for system agents`).

## Session 2026-05-27 (claude code) — Stage 33: pin standup chat composer to viewport bottom (planned + DONE)

Worktree `../wt-s33` (branch `s33-chat-bottom`) off `e0e23e9`.

**Added + implemented Stage 33 (S33.chat-bottom.1).** Goal: keep the standup chat **text input aligned to the bottom of the browser window, always on-screen without page-scrolling**, so attendees stay focused on the main viewport with the scrum master. The chat already lived in an `<aside>` grid column with an internally-scrolling message list and a trailing `<form>` composer, so the fix was layout-only: made the `<aside>` viewport-anchored on `xl` (`xl:sticky xl:top-5 xl:h-[calc(100vh-2.5rem)] xl:self-start`, `standup.tsx`) and added `xl:min-h-0` to the chat `Card` (`standup-chat.tsx`) so it fills the fixed-height column instead of forcing a 22rem floor — the composer now sits at the bottom edge of the visible window while history scrolls inside the card. Below `xl`, the prior flow layout is retained. No change to chat send/presence/summarize/websocket logic; Stage-27 Widen/Collapse still works (it changes column width, not sticky behavior). `cd web && npm run build` passes.

(Note: while planning this, observed the PiAgent session had already shipped Stage 31, Stage 32, and S32.github-history.1 to main — Stage 33 sits cleanly after them.)

## Session 2026-05-27 (pi) — Stage 32 follow-up planning: GitHub history → applications

Added new backlog task **S32.github-history.1** to `IMPLEMENT.md`: identity enrichment should use the resolved LDAP user email/uid to check read-only GitHub history for commits/repo interactions, list repos the user has touched, and map those repos to applications/environments via internal app environment data where available. First acceptable slice is repo listing with app mapping marked `unknown` when app data is missing; disabled/missing GitHub data must degrade cleanly.

**S32.github-history.1 DONE.** Extended the GitHub connector sample/read path with `github_user_history` and `GitHubConnector.user_history()`, deriving aliases from email/uid and aggregating commit/PR evidence by repo. `identity_enrichment` now attaches `github_history.repos[]` with interaction kinds, evidence count, latest date, examples, and `application_mapping` from the internal repo→app/environment map (or `unknown` when absent). The Stage-31 incoming ticket identity panel renders compact repo→app/env badges.

Verification: `python3 -m py_compile mcp/*.py mcp/connectors/*.py scripts/seed_ldap_users.py web/*.py`; direct `build_identity_enrichment('maya.chen@lanGarland.com')` returns `payments-api` and `payments-worker` mapped to Payments apps; `cd web && npm run build`.

## Session 2026-05-27 (pi) — Stage 32 LDAP directory + identity enrichment

**S32.ldap.1 + S32.enrich.1 + S32.s31.1 DONE.** Added `mcp/connectors/ldap.py` with `LdapDirectory` fixture mode returning python-ldap-shaped `(dn, attr-bytes)` search results, registered the connector, added `scripts/seed_ldap_users.py`, and generated `mcp/fixtures/ldap_users.json` with 200 fake enterprise users, app-team/DL groups, and a real manager chain up to `enterprise.vp`. Added LDAP env defaults to `.env.example` and `docs/ldap-directory.md`. `LDAP_ENABLED`/`CONN_LDAP_ENABLED` disabled mode degrades cleanly.

Added `mcp/identity_enrichment.py`, MCP tool `identity_enrichment`, web proxy `GET /api/identity/{user}/enrichment`, and TS types/query hook. Enrichment resolves the LDAP user, infers teams from `memberOf`, returns title/manager/team/directory summary, checks existing read-only connector summaries for activity, and creates team routing context without exposing secrets.

Wired Stage 31 incoming tickets to call identity enrichment for reporter/extracted users and render a compact "Who & team context" panel in `web/src/components/standup-incoming.tsx`.

Verification: `python3 -m py_compile mcp/*.py mcp/connectors/*.py scripts/seed_ldap_users.py web/*.py`; fixture round-trip `maya.chen@lanGarland.com → ... → enterprise.vp`; `cd web && npm run build`.

## Session 2026-05-27 (pi) — Stage 31 incoming-ticket triage bubble

**S31.intake.1 + S31.bubble.1 DONE.** Added `mcp/standup_intake.py` plus the `standup_incoming_tickets` MCP tool and authenticated `GET /api/standup/incoming` web proxy. The intake path reads existing Jira list data when available, identifies unassigned/new intake (with optional `STANDUP_INCOMING_DEMO=true` deterministic POC rows), extracts AWS account/RDS/region/app-team/user/email/DL entities, matches against backend-owned standup templates, and returns connector-hub enrichment/health without writes or secret echoing. Extended `web/standup_store.py::parse_links_mentions` to preserve the new entity arrays alongside existing links/mentions/Jira keys.

Added `web/src/components/standup-incoming.tsx`, React Query hook/types, and `/standup` integration. The conditional card is absent for zero tickets and otherwise renders ticket summary/reporter, entity chips, workflow match confidence/rationale, connector source badges, and a dry-run kickoff affordance that uses the existing standup summarize/proposal path rather than adding a new write path. Updated docs/changelog and checked both Stage-31 tasks in `IMPLEMENT.md`.

Verification: `python3 -m py_compile mcp/*.py web/*.py` and `cd web && npm run build` pass.

## Session 2026-05-27 (claude code) — Stage 21: baseline system agents (S21.agent.1)

Worktree `../wt-s21-agent` (branch `s21-agent`) off `ed2a755`.

**S21.agent.1 DONE — found + fixed the graph-agent hang.** Probing the 8-agent roster end-to-end exposed the long-standing runtime.1 issue: `mongo_agent` (and `docs_agent`) sat at `running` forever. Root cause via the installed deepagents source: a `CompiledSubAgent` runnable **must consume and return a `messages` key** (validated in `deepagents.middleware.subagents`), but `ask_data`'s `AskDataState` (`question`/`answer`) and `docs_agent`'s `DocsAgentState` have none — the orchestrator passed `{messages}` the native graph ignored (nodes read `state.question` → empty), produced no `messages`, and the run never reached a terminal state. `ask_data` standalone runs in ~19s, so it was a contract mismatch, not slowness.

Fix in `mcp/deep_agent/runtime.py`: added `_messages_adapter(run, label)` — a `MessagesState`-in/out `StateGraph` whose single node lifts the delegated task via `_last_human_text(messages)`, runs the native coroutine (`run_ask_data`→`render_markdown`, `run_docs_agent`→json), and returns the result as an `AIMessage`. `_graph_runnable` wraps both graphs through it. (Two false starts first: a function-local `TypedDict` with `Annotated[list, add_messages]` failed forward-ref resolution → `NameError` on `Annotated` then `add_messages`; settled on langgraph's prebuilt `MessagesState`.)

Added `scripts/smoke_agents.py` (roster scopes, read-only behavior, orchestrator routing, write-agent HITL pause; graph agents behind `RUN_GRAPH_AGENTS=1`).

**Verified live** (mcp rebuilt + recreated): full `smoke_agents.py RUN_GRAPH_AGENTS=1` PASS — mongo_agent now completes ~12s ("23 open tickets"), docs_agent completes, aws/servicenow read-only complete scoped (report disabled connectors, no write), orchestrator routes, atlassian pauses at `interrupt_on` (`jira_apply_staged`/`canApplyJira`). No regressions: `smoke_ask_data.sh` 3/3, `smoke_agent.sh`, `smoke_agent_hitl.py`. Unblocks S21.extend.1 and S21.verify.1.

## Session 2026-05-27 (claude code) — planned Stage 32 (LDAP directory module + identity-driven hub enrichment)

**Added Stage 32 to `IMPLEMENT.md`** (planning only — no code): an enterprise **LDAP directory module** (email/name/groups/manager/hierarchy/position) modeled on a live `python-ldap` + app-ID bind but **faked** for the POC, returning the entities a real bind+search would, against a **200-user fixture** with common enterprise attributes; plus **identity-driven enrichment** that, given a resolved user, searches the Compliance Hub connectors for recent activity, infers their team(s), and pulls team context (Confluence overviews/technical pages, ServiceNow assignment groups) to guide assistance/routing. First consumer is Stage 31.

Three tasks: **S32.ldap.1** (new `mcp/connectors/ldap.py` connector-shaped directory module + `scripts/seed_ldap_users.py` 200 users with cn/displayName/mail/title/department/manager-chain/memberOf/employeeID/location/DLs + `ldap_lookup_user`/`ldap_lookup_manager_chain` MCP tools; live path stubbed); **S32.enrich.1** (`mcp/identity_enrichment.py` + `identity_enrichment` tool + `GET /api/identity/{user}/enrichment` — team inference + activity/context via existing read-only connector tools); **S32.s31.1** (wire enrichment into the Stage-31 incoming-tickets bubble so each ticket shows its reporter's identity/team/context).

**Key design boundary recorded:** the Stage-19 auth `DirectoryAdapter` (`web/auth_ldap.py`) stays at its minimal 6-key RBAC contract; the richer enrichment fields (manager/hierarchy/position/DLs/etc.) live in the **new MCP-side module** used for context, never authorization. All lookups read-only via existing connector tools; no secrets/bind-creds ever echoed; live-LDAP swap is a drop-in. Worked in worktree `../wt-s32` (branch `s32-ldap-enrichment`) off `aace658`, per COORDINATION rule 2.

## Session 2026-05-27 (claude code) — planned Stage 31 (standup incoming-tickets triage bubble)

**Added Stage 31 to `IMPLEMENT.md`** (planning only — no code): a conditional **"Incoming tickets"** bubble in the `/standup` main section that surfaces new unassigned/unaddressed Jira tickets routed to the team, analyzes each against known on-boarding/consultation workflows, and enriches it by extracting entities (aws_account, rds_instance, aws_region, app_team_id, users, emails, distribution_lists) and looking them up across the Compliance Hub connector modules (AWS/ServiceNow/GitHub/Mongo) so the scrum master can decide handling/assignment fast and kick off a matched workflow as a dry-run proposal.

Two tasks: **S31.intake.1** (backend — `standup_incoming_tickets` MCP tool over existing `jira_search_issues` reads + `parse_links_mentions` entity extension + workflow match against `standup_templates`/`workflow/` + connector enrichment via existing read-only connector tools; `GET /api/standup/incoming` proxy) and **S31.bubble.1** (the conditional cockpit card in the main `<section>` + one-click dry-run workflow kickoff into the Stage-25 approver gate). Grounded in real surfaces (standup.tsx:363 main section, connector tool names, `parse_links_mentions` at standup_store.py:88). Strictly read-only intake + analysis + dry-run proposal; no auto-assign/write outside the Stage-25 Submit gate. Depends on S20/S23/S24/S25/S27. Worked in worktree `../wt-s31` (branch `s31-incoming-tickets`) off `f356acf`, per COORDINATION rule 2.

## Session 2026-05-27 (claude code) — Stage 20 closeout (S20.chat.2)

**S20.chat.2 DONE — verified already-fixed, no code change.** Traced the optimistic/echo duplicate end to end: the dedup is handled by **client-id reconciliation** that is already wired through all three layers — send carries the optimistic `id` (`standup-chat.tsx:610`) → server reads it as `client_message_id` (`standup_ws.py:410`) → persisted (`standup_store.py:164`) and echoed → `normalizeMessage` lifts it to `clientMessageId` → `mergeMessages` builds `clientToServerId` and drops the local `pending` row when its echo arrives, marking the survivor `pending:false`/`deliveryStatus:"sent"`. User confirms the dupe no longer reproduces in current builds. Closed as a docs/checkbox flip only (the user-facing fix is already in the CHANGELOG: "sender-side optimistic messages are acknowledged in place"). `cd web && npm run build` clean; `scripts/smoke_standup_ws.py` passes (join/chat-echo/RBAC/dry-run approval/snapshot). **Stage 20 now fully complete.**

## Session 2026-05-26 (claude code) — Stage 21: HITL interrupt/resume contract (S21.hitl.1)

Worktree `../wt-s21-hitl` (branch `s21-hitl`) off HEAD `ec5a3ec`.

**S21.hitl.1 DONE.** The runtime had the HITL *scaffolding* (ApprovalRequest, checkpointer, resume skeleton) but two real bugs blocked it, found by reading the installed `langchain.agents.middleware.human_in_the_loop` source: (1) `_extract_interrupt` read `val["tool"]`/`val["rationale"]`, but deepagents 0.6.3 interrupts with a `HITLRequest` = `{action_requests: [{name, args, description}], review_configs: [...]}`, so the approval payload came out empty; (2) `agent_run_resume` sent `Command(resume="reject"|decision)`, but the middleware consumes `interrupt(req)["decisions"]` — a list of `{"type": "approve"|"reject"|"edit", ...}`, one per action.

Fixes in `mcp/deep_agent/runtime.py`:
- `_extract_interrupt` parses the `HITLRequest` → typed `ApprovalRequest` (`tool`, args `payload`, `rationale`); added `required_capability` (resolved via `_capability_for_tool` from the owning profile's `write_tools`/`required_capability`) and `action_count`.
- `_normalize_decision` + `_build_resume_decisions` translate approve/reject/edit into the middleware's `{"decisions": [...]}` shape (one per pending action).
- `agent_run_resume(run_id, decision, actor, actor_capabilities)`: enforces the capability gate before approve/edit (`PermissionDeniedError`, distinct from ValueError); when `DEEP_AGENT_DRY_RUN_ONLY` is on, downgrades approve→no-write reject (read fresh per-resume via `_dry_run_only()`).
- `mcp/server.py`: resume tool gains `actor_capabilities`; PermissionDenied → envelope `code:"forbidden"`.
- `web/main.py`: resume proxy passes `sorted(user.capabilities)`; maps `code:"forbidden"` → HTTP 403.
- `web/src/routes/agents.tsx` + `types.ts`: approval panel shows `required_capability`, disables Approve when the user lacks it.
- `scripts/smoke_agent_hitl.py` (new); `docs/deep_agent_platform.md` §7 updated to the implemented contract.

**Verified LIVE** (rebuilt sglandsimple-mcp from the worktree, recreated container, healthy): pause→`waiting_approval` with `tool=jira_apply_staged`/`cap=canApplyJira`; approve-without-cap → forbidden; approve-with-cap under dry-run → applied nothing ("write wasn't applied because dry-run"); a separate paused run survived `docker compose restart mcp` and resumed (reject→`rejected`) cleanly. `smoke_agent.sh` and `smoke_ask_data.sh` (3/3) still pass. `py_compile` + `npm run build` clean.

## Session 2026-05-26 (claude code) — Stage 26: chat runtime visibility (S26.chat-runtime.1)

Worked in worktree `../wt-s26` (branch `s26-chat-runtime`) branched from HEAD `08147da`, per COORDINATION.md rule 2 (PiAgent worktrees active).

**S26.chat-runtime.1 DONE** — the `/chat` page exposes a read-only **Runtime routing** panel: the public chat agent's provider/model/redacted-endpoint plus the Deep-Agent orchestrator and per-agent model assignments.
- `mcp/llm.py`: added `role_runtime(role)` returning a redacted descriptor (provider / host+path endpoint / model / max_tokens / `inherits_default`); `_redact_endpoint` strips credentials + query, `_provider_for` infers a provider label (or honors `<PREFIX>_PROVIDER`). No API keys are ever returned.
- `mcp/deep_agent/runtime.py`: factored the inline role-resolution (`_subagent_role`, `_orchestrator_role`) used by `_compile_subagent`/`build_orchestrator`, and added `runtime_info()` mapping the orchestrator + each profile to its resolved role's redacted runtime.
- `mcp/server.py`: new `chat_runtime_info` tool (def + dispatch + `_tool_chat_runtime_info` handler) — `chat_agent` = `default` role (what the public agent service uses), `platform` = `runtime_info()`, degrades gracefully if the deep-agent package fails to import.
- `web/main.py`: `GET /api/chat/runtime` proxy, guarded by `CAN_READ_CHAT` (read-only for any chat reader); unauthed → 401.
- Frontend: `ChatRuntime*` types + `useChatRuntime` hook (append-only); a `RuntimePanel` in `chat-assistant.tsx` shown in the left rail. Admins (`canAdminAuth`) see a clearly-marked, non-functional "admin · model routing" affordance noting the future control path (validated allowlist + audit + rollback, no secrets); non-admins see a "keys never exposed" note. No mutation endpoint added.
- Docs: `docs/clients.md` gained a `chat_runtime_info` section (curl + redaction note); `CHANGELOG.md` Added entry.

**Validation:** `python3 -m py_compile agent/*.py mcp/*.py mcp/deep_agent/*.py web/*.py` passed; `cd web && npm run build` (tsc + vite) passed; verified `_redact_endpoint` strips embedded credentials and query strings (`https://user:secret@llm.lan:8000/v1?key=abc` → `llm.lan:8000/v1`). Runtime import-level smoke of `runtime_info()` not run on host (langgraph/langchain live only in the mcp image); covered by py_compile + isolated redaction test.

## Session 2026-05-26 (pi agent) — Stage 30 planned (multi-agent hygiene enforcement) + gitblockhook.md + S29 web deploy

**Why:** the parallel **PiAgent** session worked the shared main tree instead of its own worktree (COORDINATION.md rule 2) and left a broken `chat-assistant.tsx` uncommitted that broke `npm run build`. Prose rules didn't hold; need mechanism.

**Added Stage 30 to `IMPLEMENT.md`** (planning): S30.cc-hooks.1 (Claude Code SessionStart + PreToolUse deny of broad git forms), S30.git-hook.1 (shared `pre-commit` syntax guard via `core.hooksPath` — the cross-agent backstop that binds PiAgent too), S30.allowlist.1 (tighten the blanket `Bash(git add *)` grant). Documented the two-layer architecture: `.claude/` hooks are Claude-Code-only AND gitignored here (`.gitignore:15`), so the cross-agent enforcement must be the tracked git hook.

**Delivered `gitblockhook.md`** (repo root) per user request: a single self-contained doc with all scripts/settings inlined (`.claude/settings.json`, `block-broad-git.sh`, `session-start.sh`, `scripts/git-hooks/pre-commit`, `scripts/install-git-hooks.sh`), verify steps, a file manifest, and a "what PiAgent must build itself" section. The user will have PiAgent build from this. I also created the live `.claude/` hooks locally for this session (gitignored, tested: 5 deny forms deny, 4 legit forms allow); they are not committed.

**Resumed prior work:** PiAgent finished + pushed its WIP as `c77fc1d feat(S22): newest-first feed…` on top of my `444bf51`. Local==remote. `npm run build` now clean. Confirmed my S29 changes survived the merge (`/api/standup/gates` + toggle UI present). **Rebuilt + redeployed the `web` container** (was blocked by PiAgent's broken file): healthy on :5452, `/` → 200, `GET /api/standup/gates` → 401 unauth (auth gating verified). S29 admin toggle is now live.

## Session 2026-05-26 (pi agent) — Stage 29 planned + S29.gate-toggle.1 implemented

**Answered the user's question first:** traced the apply path end-to-end. `jira_edit` proposals DO execute live when all three gates open (`web/standup_ws.py::_apply_proposal_submit` → MCP `jira_apply_staged` → `mcp/connectors/jira.py::_live_update_issue` hits hosted Atlassian). But `new_jira_work`/comments hit the "no supported production apply tool" branch — approved, never executed. And proposals never get cleared (no delete/dismiss anywhere in `standup_store.py`). So: scaffold needed for create/comment + lifecycle.

**Added Stage 29 to `IMPLEMENT.md`** (planning): S29.lifecycle.1 (dismiss/archive/clear decided proposals), S29.apply.1 (extend production apply to Jira create + comment), S29.gate-toggle.1 (admin dry-run toggle). Documented the verified gate-architecture constraint: `STANDUP_DRY_RUN_ONLY` is read per-request in the **web** process (toggleable live) while `WORKFLOW_WRITES_ENABLED`/`JIRA_WRITES_ENABLED` are **MCP** import-time constants (need restart) — so the toggle can only flip the web gate, and that's the safety interlock.

**Implemented S29.gate-toggle.1:**
- `web/standup_ws.py`: in-process `_dry_run_only_override` + `_dry_run_only()` helper (override > env); `_apply_proposal_submit` now reads `_dry_run_only()`. New `GET /api/standup/gates` (any authed user, effective state incl. `live_writes_effective`) and `POST /api/standup/gates` (`Depends(require_capability(CAN_ADMIN_AUTH))`, flips the web gate only, appends a `_gate_audit` entry with actor/before/after/ts).
- `web/src/lib/types.ts` + `queries.ts`: `StandupGates`/`StandupSetGatesResult` types, `useStandupGates()` query + `useSetStandupGates()` mutation (append-only).
- `web/src/routes/standup.tsx`: in the config/trace card, a live "Effective live writes" panel showing all three gates (web vs mcp tagged); admins (`canAdminAuth`) get a Disable/Re-enable dry-run button with an explicit note that the two MCP gates are independent + need a restart; non-admins see read-only.

**Verification:** `python3 -m py_compile web/standup_ws.py` passes. `npx tsc -b` shows my files (`standup.tsx`, `queries.ts`, `types.ts`) **clean**. NOTE: `npm run build`/docker `web` build currently FAILS, but only on `web/src/components/chat-assistant.tsx` — an **uncommitted parallel-session WIP** (alongside uncommitted `mcp/ask_data.py`, `mcp/server.py`, `markdown.tsx`, `package.json` that I did not touch). Per COORDINATION.md I staged only my own files by name and did not sweep theirs. Docker `web` rebuild deferred until that WIP compiles.

## Session 2026-05-26 (pi agent) — Stage 28 planned: multi-session chat + AI extraction

Added **Stage 28** to `IMPLEMENT.md` (planning only, no code yet). Two tasks:
- **S28.chat-sessions.1** — New-chat button + session switcher on `/standup`. Reuses the existing arbitrary-`session_id` `StandupStore`; adds a `GET /api/standup/sessions` list endpoint + `StandupStore.list_sessions()`, makes `StandupChat`'s `sessionId` controlled so switching tears down/reopens the websocket. No stored-schema change.
- **S28.ai-extract.1** — an **"AI"** button (distinct from Summarize) that extracts a structured brief (participant/user identity, referenced tickets, detected config items + related config JSON pulled via existing read-only connector tools, user-requested actions) and emits dry-run **proposals phrased as approver instructions** (e.g. "Create a new Jira ticket under Epic XYZ…", "Update ABC-12 to Blocked per chat", "Add a comment to ABC-1234 with the AWS config pulled for that resource"). Built as an enrichment over `mcp/standup_agent.py::run_standup_summarize` / the `standup_summarize` tool, **not** a new agent; everything stays dry-run and flows through the Stage-25 approver Save/Submit gates. Degrades to a placeholder like `_handle_agent_summarize` on failure; smoke `scripts/smoke_standup_ws.py` to be extended for an `agent.extract` round-trip.

Researched the existing surface first (`web/standup_ws.py`, `web/standup_store.py`, `mcp/standup_agent.py`) so the task references real files/functions and the "Reuse, don't reinvent" note is accurate. Updated the open-work summary line. No CHANGELOG entry (planning note, per CLAUDE.md).

## Session 2026-05-26 (pi agent) — Stage 27: widenable standup chat + main-grid reference rail

Added **Stage 27 (S27.layout.1)** to `IMPLEMENT.md` and implemented it. Goal: improve `/standup` screen-share ergonomics.

- `web/src/components/standup-chat.tsx`: added optional `expanded`/`onToggleExpand` props and a header **Widen/Collapse** button (Maximize2/Minimize2 icons, `aria-pressed`). Layout is parent-controlled; chat send/presence/Summarize unchanged.
- `web/src/routes/standup.tsx`: new `chatExpanded` state. Outer grid switches between `xl:grid-cols-[minmax(0,1fr)_23rem]` (collapsed) and `grid-cols-1` (widened); when widened, the chat aside is `order-1` (full width on top) and the main section `order-2`. Moved **Epics** and **Approvals viewport** out of the right aside into the main left section as a `lg:grid-cols-2` two-up grid (below Jira Explorer / config-trace / Templates). The right aside is now chat-only.
- **Jira Configuration / tool trace** card already always renders its header/card as a stable section item; only its `CardContent` is toggled, so its show/hide no longer reflows the grid. Documented this guarantee.
- Updated `docs/standup.md` and `CHANGELOG.md`; flipped the S27.layout.1 checkbox.

**Verification:** `cd web && npm run build` passed (tsc + vite; pre-existing chunk-size warning only). No backend/`.py` changes, so no py_compile needed.

**Git:** committed `691b9b0` and pushed to `main`; `web` image rebuilt + redeployed (`docker compose build web && up -d web`, healthy on :5452).

**Follow-up (same session):** per user feedback, **Widen no longer collapses to full-width**. The outer grid stays two-column in both states; widening just swaps the chat track from `23rem` → `69rem` (3×), main section keeps `minmax(0,1fr)`. Removed the `grid-cols-1` collapse and the `order-1`/`order-2` reshuffle. Updated `docs/standup.md` + `CHANGELOG.md` wording. Build passes. (committed `8df6954`, pushed by user.)

**Follow-up 2 (same session):** per user, reordered the main section to **Jira Explorer → Epics + Templates (two-up `lg:grid-cols-2`) → Approvals viewport (full-width) → Jira Configuration / tool trace (moved to bottom)**. Previously Epics paired with Approvals and the config/trace card sat directly under Jira Explorer. Also added an inline **How to use this** numbered guide to the Approvals viewport (capture chat → Summarize → review/edit payload → Save → Submit/Reject, with a read-only notice for non-approvers) and simplified its `CardDescription`. `web/src/routes/standup.tsx` only; `docs/standup.md` + `CHANGELOG.md` updated. `cd web && npm run build` passes.

## Session 2026-05-26 (pi agent) — Standup layout follow-up: chat top, templates bottom

Adjusted `/standup` layout for screen-share ergonomics:
- `web/src/routes/standup.tsx`: moved `StandupChat` to the **top of the right-hand column** so live note capture and Summarize stay first in the vertical flow.
- Moved `StandupTemplatesCard` out of the right-hand column and into the **bottom of the main viewport**, directly below the Jira Explorer and Jira Configuration/tool trace section.
- Left `StandupEpicsCard` in the right-hand column below chat so selected-epic context still sits near the live conversation.
- Updated `docs/standup.md` and `CHANGELOG.md` to describe the new layout.

**Verification:** `cd web && npm run build` passed; `python3 -m py_compile web/*.py` passed.

## Session 2026-05-26 (pi agent, yolo) — S21.runtime.1 PARTIAL + handoff

**S21.runtime.1 PARTIAL (MCP side landed).** Added the 6 `agent_*` MCP tools (defs + registration in `TOOLS` + dispatch in `_dispatch_tool`) and the typed runtime in `mcp/deep_agent/runtime.py` (`AgentRunStartRequest`/`ApprovalRequest`/`AgentRunRecord`; `agent_run_start/status/resume/cancel/artifacts`; `agent_profiles_list`). Runs persist to `DEEP_AGENT_RUN_COLLECTION`; orchestrator compiled with the Mongo checkpointer for resume/restart. **Verified live:** `tools/list` shows all six; `agent_profiles_list` returns the 8-agent roster; `agent_run_start` **creates a Mongo run record**.

**Known issue / handoff:** `agent_run_start` left the run at `status="running"` — the orchestrator `ainvoke` didn't finish in the request window. Likely (a) real LLM routing + subagent hops exceed the curl/proxy timeout, and/or (b) the `CompiledSubAgent`-wrapped `ask_data` graph expects `{question}`/`AskDataState`, not the deep-agent `{messages:[...]}` input — the orchestrator→subagent input contract needs validating (that's `S21.agent.1`). Fix forward: give `agent_run_start` a deadline + background execution (return run_id immediately, poll status), and reconcile the graph-subagent input shape. **Web `/api/agents/*` proxies + TS types/hooks not yet added.** Marked S21.runtime.1 `[~]` in IMPLEMENT.md with full remaining notes.

**Stage-21 status:** arch.1, upgrade.1, profile.1, context.1, orch.1 DONE & on main; runtime.1 PARTIAL; hitl.1/agent.1/extend.1/ui.1/deploy.*/bedrock/obs/security/verify.* OPEN. Next picker: finish runtime.1 (input contract + background exec + web proxies), then hitl.1.

## Session 2026-05-26 (pi agent, yolo) — S21.orch.1 (orchestrator + allowlist)

**S21.orch.1 DONE.** Added `build_orchestrator()` to `mcp/deep_agent/runtime.py`: compiles validated profiles into a `create_deep_agent` thin router (tools=[], delegates via the built-in `task`). Non-graph profiles → subagent dicts with `StructuredTool`s wrapping `server._dispatch_tool`; graph profiles → `CompiledSubAgent` over `ask_data.build_graph()`/`docs_agent.build_docs_agent_graph()`. Per-tool allowlist enforced in the wrapper (out-of-allowlist call fails closed + records a `policy_events()` entry). Model = configured `chat_model(role=)` (our upstream, not a provider string). `_live_tool_names()` includes connector *classes* so disabled-connector tools are valid config; unknown tools fail fast. Verified in-container: orchestrator builds to CompiledStateGraph over all 8 agents; denied tool call fails closed + logs policy event. Next: S21.runtime.1.

## Session 2026-05-26 (pi agent, yolo) — Stage 25 completed (approver viewport + production submit) + Stage 24 completed

**Stage 25 DONE.** Implemented the production-approvals viewport:

- `web/standup_ws.py`: added `_standup_approver_emails()` reading `STANDUP_APPROVER_EMAILS` (default `simone.patel@lanGarland.com`); `_can_approve()` now also resolves named approver emails case-insensitively so approval is auth-system-bound, not UI-only. Submit (`proposal.approve`) became the production-apply gate: it re-stages/revalidates Jira edits, and only calls `jira_apply_staged` when all three gates are open (`STANDUP_DRY_RUN_ONLY=false`, `WORKFLOW_WRITES_ENABLED=true`, `JIRA_WRITES_ENABLED=true`). Otherwise it records a blocked/validated result.
- `web/standup_store.py`: audit capture now records `original_payload` and `edited_payload` on each approval for later review and rollback. Edits also preserve `original_dry_run_payload`.
- `web/standup-chat.tsx`: added `edit` control so the parent route can wire Save and Submit.
- `web/src/routes/standup.tsx`: renamed "Approval tray" to "Approvals viewport", added an editable `textarea` for each proposal's JSON payload with live validation, **Save** (sends `proposal.edit` via websocket), **Submit** (Sends `edit` then `approve`), and **Reject** controls. Disabled for non-approvers/with tooltips. Added JSON-parse validation before enabling Save/Submit.
- `.env.example`: added `STANDUP_APPROVER_EMAILS`.
- Updated `docs/standup.md` and `CHANGELOG.md`.

**Verification:** `python3 -m py_compile web/*.py scripts/smoke_standup_ws.py` passed. `cd web && npm run build` passed (pre-existing chunk-size warning only).

## Session 2026-05-26 (pi agent, yolo) — Stage 24 completed (standup reference rail + shared templates)

**Stage 24 DONE.** Pulled first (`git pull --ff-only origin main`, already up to date) and preserved pre-existing dirty files. Implemented the `/standup` reference rail:

- `GET /api/standup/epics` returns read-only active epics from the `epics` collection via MCP `mongo_query`, honoring `STANDUP_EPICS_ACTIVE_ONLY`/`STANDUP_EPICS_LIMIT` and normalizing the Stage-24 fields (`epic_key`, `jira_key`, title, program area, status, priority, tags, regulation refs, DB/platform combos, ticket refs, finding ids).
- Added `mcp/standup_templates.py` plus the `standup_templates` MCP tool and `/api/standup/templates` proxy. This is the Stage-24/Stage-21 convergence point: a plain backend-owned store consumed by both the UI prompt preview and the Stage-21 Deep Agent context-pack seam, with no duplicated prompts in frontend or agent code.
- Added typed React Query hooks/types (`useStandupEpics`, `useStandupTemplates`, `StandupEpic`, `StandupTemplate*`).
- Updated `/standup` with two collapsed-by-default cards: **Epics** (active epic rows, Jira deep links, classification chips, per-row details, selected-epic context seam) and **Templates** (read-only field-spec table + backend-sourced prompt dropdown rendered through the existing `Markdown` component). No new Markdown dependency.
- Documented deferred editability in `docs/standup.md`: future inline epic-field editors and audited template upsert can replace the presentational cells/store without rewriting the page.
- Added Stage-20/Stage-24 env defaults to `.env.example`, updated `CHANGELOG.md`, and flipped all `S24.*` tasks to done in `IMPLEMENT.md`.

**Verification:** `python3 -m py_compile mcp/*.py web/*.py scripts/*.py` passed. `cd web && npm run build` passed (pre-existing chunk-size warning only). No live external writes or reseed run.

## Session 2026-05-26 (pi agent) — Stage 26 planned (chat runtime visibility)

Planning/docs-only task added per user request. Added **Stage 26 — Chat runtime visibility and admin-selectable model routing (planned)** to `IMPLEMENT.md` with task `S26.chat-runtime.1`.

Task captures: focused `/chat` should show the active agent endpoint/provider/model plus Deep-Agent/subagent routing details (orchestrator and system agents), with secrets redacted and values sourced from a server-side runtime-info API/MCP tool. Normal users get read-only visibility; admins get a clearly marked future-control affordance for provider/model selection, but no mutation endpoint in the first slice. Also documented the future admin override path: validated allowlist, audit log, rollback, and no secrets in JSON payloads.

Git handoff is documented directly in the task following `COORDINATION.md`: pull first, stage named paths only (never `git add -A`/`.`/`commit -a`), inspect `git status --short` and `git diff --cached --stat`, commit with a focused `feat(S26): ...` message, push feature branch, and merge by PR or fast-forward only after review/smokes. No build run for this docs-only task addition.


## Session 2026-05-26 (pi agent, yolo) — S21.context.1 (context packs)

**S21.context.1 DONE.** Added `mcp/deep_agent/context.py`: named, versioned `ContextPack`s (`jira_story_template` v1, `standup_labels` v1) sourced from existing Stage-20 material (`build_story_template_context`, `ACCEPTANCE_CRITERIA_FORMAT`, `DEFAULT_STANDUP_LABELS`) — no duplicated prompts. `render_packs()` emits a compact block per pack; unknown packs raise; `validate_profile_packs()` cross-checks profiles. Stage-24 convergence seam `_try_standup_templates_store()` prefers the shared store, falls back to in-repo. Verified in-container: packs render, unknown rejects, all profile pack refs clean. Next: S21.orch.1.

## Session 2026-05-26 (pi agent, yolo) — S21.profile.1 (agent profile schema + loader)

**S21.profile.1 DONE.** Added `mcp/deep_agent/profiles.yaml` (orchestrator + 8 one-per-system agents: atlassian/mongo/github/servicenow/aws/audit/docs/standup, referencing real MCP + connector tool names) and `mcp/deep_agent/profiles.py` (Pydantic schema + fail-fast loader). Validation enforces: write_tools ⊆ allowed_tools, no reserved runtime tools, read_only⇒no writes, write_tools⇒a Stage-19 capability, graph-backed⇒no allowed_tools, unique names. `interrupt_on()` builds the deepagents per-tool HITL map; `graph:` marks mongo→ask_data / docs→docs_agent as future CompiledSubAgents; `DEEP_AGENT_PROFILES_FILE` honored; `validate_against_catalog()` defers live-tool checks to runtime. Module imports only pydantic+yaml (no deepagents at load). Verified in-container: 8 agents load, interrupt_on correct, 5/5 negative cases reject, catalog check flags unknown tools. Added `DEEP_AGENT_PROFILES_FILE` to `.env.example`. Next: S21.context.1.

## Session 2026-05-26 (pi agent) — S21.upgrade.1 (LangChain 1.x + deepagents) on branch `stage-21-langchain-upgrade`

Started Stage 21 implementation on a new branch. **S21.upgrade.1 DONE.**

- **Resolved a conflict-free version set** by dry-run resolving `deepagents` against our deps in a throwaway venv: `deepagents==0.6.3`, `langchain-core==1.4.0`, `langchain==1.3.1` (transitive), `langchain-openai==1.2.2`, `langgraph==1.2.1`, `langgraph-checkpoint-mongodb==0.4.0`, `openai==2.38.0`, `tiktoken==0.13.0`. Had to **relax `motor` to `>=3.7,<4`** (checkpoint-mongodb 0.4.0 requires `pymongo>=4.12`, blocked by the old `motor==3.6.0`) and `pydantic>=2.10,<3`. Verified the full set (incl. snowflake/fpdf2/pptx) resolves with no conflicts.
- **One real API break, fixed:** checkpoint-mongodb 0.4.0 dropped `langgraph.checkpoint.mongodb.aio.AsyncMongoDBSaver`. The unified `MongoDBSaver` serves the async checkpointer interface but its `from_conn_string` is a **sync** `@contextmanager` — first attempt `async with` failed at runtime (`'_GeneratorContextManager' object does not support the asynchronous context manager protocol`, caught by `smoke_deep_agent.sh`). Fixed `mcp/checkpointer.py` to enter it with `with` inside our `@asynccontextmanager`. `mcp/llm.py` unchanged (raw `openai` SDK + basic `ChatOpenAI` ctor, stable across versions). Dockerfile unchanged (py3.12 already).
- **Verified live** (mcp rebuilt + recreated, healthy, clean startup logs): container import-smoke of every langchain/langgraph module + `server` + `deepagents` = 0 failures; `smoke_deep_agent.sh` PASS (planner/builder + Mongo checkpointer + sandbox + persistence); `smoke_ask_data.sh` 3/3; docs-agent HITL fresh→`waiting_approval`, resume `reject`→`completed` (0 applied) — exercises `interrupt`/`Command(resume)`/`MemorySaver`; `smoke_agent.sh` PASS; `smoke_workflow.sh` PASS. Stage-4 fallback not needed.
- **Sandbox container (user request, "if necessary"):** added an **opt-in** `sandbox` runtime service — `sandbox-runtime/Dockerfile` (non-root uid-1000, shares `./sandbox`), gated behind a `sandbox` compose profile so `docker compose up` is unchanged (verified: default profile lists mongo/mcp/agent/web; `--profile sandbox` adds sandbox). Built + started + confirmed non-root + shared mount, then stopped (opt-in shouldn't linger). It idles until the Stage-21 sidecar runtime (`S21.deploy.1`) gives it an entrypoint; `DEEP_AGENT_RUNTIME_MODE=sidecar` is its hook. Added `DEEP_AGENT_RUNTIME_MODE`/`DEEP_AGENT_ARTIFACT_DIR`/`DEEP_AGENT_DRY_RUN_ONLY` to `.env.example`; CHANGELOG updated; design doc deployment note updated.

Branch `stage-21-langchain-upgrade`; not yet merged to main. Next: `S21.profile.1`.

**Stage-24 validation against the architecture change (same session, user request):** reviewed all six S24 tasks against the deepagents adoption + LangChain 1.x upgrade. Finding: the epics-read tasks (S24.api.1/epics.1/verify.1) are unaffected (plain `epics` reads + UI; no langchain imports). The one intersection is the templates prompt library — under deepagents the `atlassian_agent` generates the same Jira/Confluence artifacts these prompts describe, and agents load prompts as context packs (`S21.context.1`). Resolution (no tasks added/removed): the Stage-24 `standup_templates` backend store is now the **shared source of truth** consumed by both the panel preview and the Stage-21 agent context packs; added a convergence constraint to `S24.templates.api.1` (keep it a plain data store, don't duplicate into agent code), a bidirectional note on `S21.context.1`, an architecture note in §24b/§24c, and a validation banner atop Stage 24. The LangChain bump itself doesn't touch Stage 24.

## Session 2026-05-26 (pi agent) — S21 design revised to deepagents SDK + roster + contributor guide

Revisited S21.arch.1 against the LangChain `deepagents` overview (fetched the overview + subagents pages) and our current deps. User decisions: **adopt `deepagents`** as the runtime, and **one agent per external system** (read/write gated per-tool via `interrupt_on` + `write_policy`, not separate reader/writer agents).

- Rewrote `docs/deep_agent_platform.md`: SDK→goal mapping (subagent `tools`/`model`/`system_prompt`/`interrupt_on`/`skills`, the built-in `task` delegation + isolated context, `CompiledSubAgent` to wrap existing graphs); the **one-per-system roster** (orchestrator router + atlassian/mongo/github/servicenow/aws/audit/docs/standup); the **gating cost** — `deepagents 0.6.3` needs `langchain>=1.3`/`langchain-core>=1.4` but we're pinned at `0.3.28`/`langgraph 0.2.62`, so a 0.3→1.x upgrade is required first; Stage-4 fallback recorded. Added **§14 "contributor's guide"** per user request: notes + justifies every platform/agent/implementation decision from a learning perspective for varied-experience adopters, plus a step-by-step "add a new agent (WAF/Splunk/Datadog)" recipe.
- Retasked the Stage-21 checklist: added `S21.upgrade.1` (LangChain 1.x + deepagents, gated by existing smokes regressing green), reframed `profile.1`/`context.1`, replaced `policy.1` with `S21.orch.1` (orchestrator + per-tool allowlist), reframed `hitl.1` to `interrupt_on`, `agent.1` to the system roster + `CompiledSubAgent` reuse, added `S21.extend.1` (prove config-only agent add), and fixed `bedrock.1`/`security.1`/`verify.1` wording to the new model. Added a decision-banner above the checklist.

New Stage-21 dependency chain: arch.1 → upgrade.1 → profile.1 → context.1 → orch.1 → runtime.1 → hitl.1 → agent.1 → extend.1; ui/deploy/bedrock/obs/security/verify hang off as before. Docs/planning only; no build run.

## Session 2026-05-26 (pi agent) — S21.arch.1 (Deep Agent platform design doc)

Started Stage 21. **S21.arch.1 DONE** — wrote `docs/deep_agent_platform.md`, the design doc that gates the rest of the `S21.*` chain. Grounded it in the actual Stage-4 code (read `mcp/deep_agent/{__init__,models,planner,catalog}.py` + the server tool wiring) rather than the spec's idealized shape:
- Identifies the **central refactor seam**: `mcp/deep_agent/catalog.py` today exposes one global catalog filtered only by a hardcoded `_EXCLUDED` recursion denylist; Stage 21 replaces "one global denylist" with "**one allowlist per profile**" (catalog functions become profile-scoped; the recursion guard stays as a floor).
- Documents: keep/change table vs Stage 4; the `profiles.yaml` profile schema + 7 baseline profiles (jira/docs/architecture/audit/workflow/auth/standup) with non-overlapping tool scopes and Stage-19 capability gates; context packs sourced from existing material; the typed HITL interrupt/resume contract (reuses the Stage-14 docs-agent checkpointed-StateGraph pattern, survives restart); the `agent_run_*` runtime API + `/api/agents/*` proxies; security/audit/redaction/observability; `DEEP_AGENT_RUNTIME_MODE` in_mcp→sidecar→remote (ECS/Fargate, K8s, Bedrock) deployment path; on-rails future direction; env surface; verification intent; task map.
- Cross-references `docs/deep_agent.md` (Stage 4) instead of duplicating it.

Flipped `S21.arch.1` to `[x]` in `IMPLEMENT.md` with a completion note. Docs-only; no build run.

Remaining Stage 21 (all blocked on this doc's downstream chain): S21.profile.1 → policy.1/context.1 → runtime.1 → hitl.1/ui.1 → agent.1 → security.1/obs.1/deploy.1 → deploy.2/bedrock.1 → verify.1/verify.2.

## Session 2026-05-26 (pi agent) — Stage 24 planned (standup Epics + Templates reference rail)

Planning-only session: added **Stage 24 — Standup reference rail: foldable Epics + Templates panels** to `IMPLEMENT.md` (no code yet). Two new collapsible cards for `/standup`, both read-first/additive:
- **Epics panel** — live read of the active `epics` collection (reuse `overview_summary`'s active notion); shows key/title/program_area/status/priority/tags/regulation_refs/db_platform_combos/ticket_refs/finding_ids with Jira deep links, for quick story creation/triage/reclassification mid-standup.
- **Templates panel** — (1) a read-only per-epic customized-fields table built off a typed field-spec + presentational cell component so a future editor drops in, and (2) a prompt/template library (dropdown + Markdown viewport via the existing `Markdown` component) sourcing ticket/Confluence-doc generation prompts from a backend-owned store — the same source `tool_calls` execute. Editing of both is explicitly deferred to a future stage; seams left in place.

Tasks added: `S24.api.1`, `S24.epics.1`, `S24.templates.api.1`, `S24.templates.ui.1`, `S24.future.1`, `S24.verify.1`. New env vars `STANDUP_EPICS_ACTIVE_ONLY`/`STANDUP_EPICS_LIMIT`/`STANDUP_TEMPLATES_ENABLED` added to the Stage-24 §24d table and the global Env-surface table. "Open work" line + COORDINATION.md ownership updated. Also added a CHANGELOG.md upkeep requirement to CLAUDE.md.

No build/compile run this session (docs only).

## Session 2026-05-23 (pi orchestrator + gpt-5.4 workers) — Stage 23 completion

Executed the full Stage-23 Confluence wire-up + cross-system enrichment stage using isolated gpt-5.4 worker subagents and integrated their diffs in main.

**Completed:**
- `S23.conn.1/S23.conn.2` — `mcp/connectors/confluence.py` now reads `CONFLUENCE_TOKEN` first (fallback `CONFLUENCE_MCP_TOKEN`), discovers hosted Atlassian MCP tools via `tools/list`, handles SSE-framed JSON-RPC/session ids, reports disabled/degraded/healthy accurately, and only performs live page create/update when `CONN_CONFLUENCE_ENABLED` + `WORKFLOW_WRITES_ENABLED` + `CONFLUENCE_WRITES_ENABLED` are true. `mcp/docs_sync.py` mirrors the same four-gate safety model; dry-run/mock idempotency remains intact.
- `S23.data.1/S23.data.2` — added `mongo-seed/15-confluence-pages.js`, added `confluence_pages` to the read-only Mongo allowlist, enriched tickets/epics/work_items/due dates across COMP/ARCH/SRE/SEC/DATA, and kept overview attention balanced so overdue/due-soon/blocked signals all appear.
- `S23.data.3` — enriched GitHub, ServiceNow, Snowflake, Archer, and AWS connector samples with shared `finding_id` / `epic_key` / `ticket_refs` overlap-chain keys while keeping existing schemas stable.
- `S23.docs.1/S23.docs.2` — added `docs/overlap-chain.md`, `docs/agentic-workflows.md`, and `docs/mcp-in-this-stack.md`; seeded concise public wiki copies in `mongo-seed/14-docs.js`; linked the teaching guides from `/architecture` and `/docs`.
- `S23.verify.1` — added `scripts/smoke_confluence.sh` for disabled/dry-run Confluence + overlap-chain verification.

**Verification:**
- `python3 -m py_compile mcp/*.py mcp/connectors/*.py web/*.py scripts/*.py` — clean.
- `node --check mongo-seed/*.js` — clean.
- `cd web && npm run build` — clean (pre-existing chunk-size warning only).
- `docker compose up --build -d mcp web` — rebuilt/restarted live services.
- `scripts/reseed.sh` — applied new seeds (note: pre-existing `12-scale-data.js` duplicate-employee warning still appears on persistent DB reseeds, but the script continues and Stage-23 seeds apply).
- `WEB_URL='http://simone.patel%40lanGarland.com:changeme-poc@localhost:5452' scripts/smoke_overview.sh` — green; KPI now shows 5 active epics and attention includes `blocked_pr`.
- `scripts/smoke_confluence.sh` — green; connector disabled path returns 6 pages, `mongo_query` finds RDS Confluence pages, teaching docs are present in the wiki, and docs sync stays dry-run without all live gates.
- `WEB_URL='http://simone.patel%40lanGarland.com:changeme-poc@localhost:5452' scripts/smoke_web_spa.sh` — green.

**Live-token note:** hosted Confluence live health/write smoke still requires operator-provided `CONFLUENCE_TOKEN` + `CONFLUENCE_MCP_URL`; no secrets were committed.

## Session 2026-05-22 (pi agent) — S22 chat layout: flip columns + compact prompt list

UX follow-up on the Stage-22 focused `/chat` page per user request: the chat needs to be readable while the suggested prompts should be compact in the left column.

**Change (`web/src/components/chat-assistant.tsx` only):**
- **Flipped the two-column layout.** The conversation feed + composer now occupy the **main wide right column** (`xl:order-2` in the `xl:grid-cols-[18rem_minmax(0,1fr)]` grid); the suggested-prompts rail is the **narrow 18rem left column** (`xl:order-1`). Previously chat was left/order-1 and the context rail right/order-2.
- **Compact list format for prompts.** Added a `variant: "chips" | "list"` prop to `PromptChips`. The new `list` variant renders prompts as a tight vertical stack of full-width buttons (small leading sparkle icon, `leading-5` text) instead of wrapped pills. The left rail now shows **Starter prompts** (fills composer) and **Direct data prompts** (runs Ask Data) both as compact lists, plus the one-line "switch to Ask Data" hint.
- Removed the duplicate starter-prompt chips from the hero header (now redundant with the left rail); hero keeps its value-prop insight cards. The `GlobalAssistant` panel and its default-`chips` `PromptChips` are unchanged.

**Verification:** `cd web && npm run build` (tsc -b + vite) clean — only the pre-existing >500 kB chunk-size *warning*. No backend/seed/connector files touched. Stage 23 remains PLANNED/not-started; this is Stage-22 polish.

## Session 2026-05-22 (pi agent) — Stage 23 PLANNED: Confluence wire-up + cross-system enrichment

Authored the **Stage 23** plan only (no implementation). Stage 23 has two threads: (1) promote the Confluence connector from mock-only to **live-capable** via a `CONFLUENCE_TOKEN` env var, mirroring the proven Stage-16 Jira live-MCP pattern (`mcp/connectors/jira.py`); (2) **cross-system data enrichment** so the POC dashboard looks lively and teachable — denser, internally-consistent seed collections + connector samples whose keys line up to form the full **overlap chain** (`archer finding → Jira epic → commit/PR → ServiceNow change → Snowflake evidence → Confluence page`), plus three process/teaching docs (overlap chain, agentic workflows, MCP-in-this-stack) for coworkers learning deep agents/agentic workflows/MCP.

**Design decisions baked into the plan:**
- `CONFLUENCE_TOKEN` is the new primary credential (user's wording); it **falls back to the existing `CONFLUENCE_MCP_TOKEN`** — no breaking rename. Live writes stay behind `CONN_CONFLUENCE_ENABLED` + `WORKFLOW_WRITES_ENABLED` + a new `CONFLUENCE_WRITES_ENABLED` guard (mirrors `JIRA_WRITES_ENABLED`). Dry-run by default.
- Enrichment is **additive only**: more rows with consistent keys, connector `schema:` fields unchanged, so `/overview`, `/architecture`, `/hub` keep rendering with no front-end changes. New `confluence_pages` Mongo collection added to `KNOWN_COLLECTIONS` (read-only traversable by Ask Data/Wrangler); the connector `_sample()` becomes a thin view over that single canonical page set.
- No orphan keys: every new `epic_key`/`finding_id`/`ticket_ref` must resolve across collections so the chain is traceable end-to-end.

**Tasks added** (`S23.conn.1`–`S23.conn.2`, `S23.data.1`–`S23.data.3`, `S23.docs.1`–`S23.docs.2`, `S23.verify.1`), all `[ ]`. Dependency-ordered; each lists Files / Done-when / Depends-on per house style.

**Docs touched this session (planning only):** `IMPLEMENT.md` (new Stage 23 section + open-stage list bump to include 23), `COORDINATION.md` (owner row: Stage 23 → pi agent, PLANNED), `progress.md` (this entry). **No code, seed, or connector files changed.** Next agent picks up `S23.conn.1` first.

## Session 2026-05-22 (pi agent) — Stage 19 finish-up: re-verify + branch cleanup

Confirmed Stage 19 is fully complete and closed out housekeeping.

**Re-verification (safe gates re-run today):**
- `python3 -m py_compile web/*.py` — clean.
- `cd web && npm run build` (tsc -b + vite) — clean (only the pre-existing >500 kB chunk-size *warning*).
- `perm/` is fully gitignored — no password hashes/secrets tracked in git. `users.json` seeds all 6 POC users across all 4 groups with PBKDF2 hashes (no plaintext).
- All 14 S19 tasks (`S19.policy.1`→`S19.verify.1`) remain `[x]` in `IMPLEMENT.md`; working tree clean.
- The live `scripts/smoke_auth.sh` end-to-end run was intentionally **not** re-run: it requires re-seeding the running `sglandsimple-web` container's `users.json` to a known password, which would clobber the operator's chosen password (and `docker exec` is blocked in this environment). The prior session's run (83 PASS / 0 FAIL / 3 SKIP, basic mode) stands.

**Branch cleanup.** All non-`main` branches were fully merged into `main` (ahead-by-0). Deleted the 4 stale merged local branches (`stage-11-overview`, `stage-14-docs-wiki`, `stage12-dynamic-overview-mockdata`, `stage9-w1`) and the 3 stale merged remote branches. **Left the 3 `pi-parallel-8f62f9a7-*` branches/worktrees untouched** — they back active parallel-agent worktrees (`/tmp/pi-worktree-*`).

## Session 2026-05-22 (pi orchestrator) — Stage 22 completion + Stage 18 closeout

Closed all Stage-22 tasks and the remaining Stage-18 architecture tasks while also carrying forward the already-dirty Stage-20 completion work.

**S22.chat.1 / S22.chat.2.** Added `web/src/components/chat-assistant.tsx` as the shared assistant surface. `/chat` now renders a polished dashboard-style focused workspace with navy/amber/teal hero, prompt chips, insight cards, context rail, upgraded transcript cards, and a composer that preserves normal chat + Ask Data. `web/src/App.tsx` renders a compact bottom assistant launcher on every non-`/chat` route; it expands into a styled dialog with quick prompts, transcript, Ask Data, and a link to the focused chat page.

**S22.wrangler.1.** `web/src/routes/wrangler.tsx` and `web/src/lib/pipeline.ts` now track field availability across successive stages. Later stages use prior successful preview fields when available, fall back to static output inference, include `$group` accumulator outputs and `$project` aliases, clear downstream previews after upstream edits, and display stale field selections with destructive styling/warnings.

**S22.brand.1.** Sidebar top-left mark now uses a Vite-managed banner asset at `web/src/assets/d6057657-40c7-4112-85fa-06322881a692.png`, with modern cropped expanded/collapsed sizing and `alt="LanGarland Fleet Dispatch"`. Added `web/src/vite-env.d.ts` for Vite asset typing.

**S18.export/docs/verify.** `/architecture` now has an Export menu for Mermaid copy plus standalone SVG/PNG downloads (`web/src/lib/arch-export.ts`) with title/timestamp/mode/legend. Architecture runbook links deep-link to `/docs?doc=...`; the known-unknowns panel links to the architecture inventory template; `/docs` initializes from that query parameter.

**Verification.** `python3 -m py_compile mcp/*.py web/*.py scripts/*.py` passed. `cd web && npm run build` passed (chunk-size warning only). `scripts/smoke_wrangler.sh`, `scripts/smoke_ask_data.sh`, `scripts/smoke_auth.sh`, and `scripts/smoke_standup_ws.py` passed.


## Session 2026-05-22 (pi agent) — Stage 20 completion (RBAC + HITL approval tray)

Closed out the four remaining Stage-20 tasks (S20.auth.1, S20.approval.1, S20.verify.1, S20.verify.2).

**S20.auth.1 — RBAC.** Added `Capability.CAN_APPROVE_STANDUP` (`canApproveStandupActions`, granted to `admin`) in `web/auth.py` + mirrored in `web/src/components/auth-provider.tsx`. Standup websocket now requires a resolved Stage-19 identity to join (closes unauthenticated clients with `1008` unless `AUTH_MODE=disabled`); snapshot proxy guarded by `require_user`; approve/reject/edit gated on the approver capability server-side (`forbidden` error otherwise). Presence carries a `can_approve` flag.

**S20.approval.1 — HITL approval tray.** `web/standup_ws.py`: capability-gated `proposal.approve`/`reject` + new `proposal.edit`; on approve, `_apply_proposal_dry_run` re-validates staged Jira edits via Stage-16 `jira_validate_staged` but never calls live apply (suppressed by `STANDUP_DRY_RUN_ONLY`). `web/standup_store.py`: `update_proposal_status` records actor/decided_at/dry_run_only/applied + validation `apply_result`; new `edit_proposal_payload` shallow-merges a dry-run payload patch on still-proposed proposals. Frontend: `StandupChat` surfaces live proposals + summarize/approve/reject controls to the parent via `onControlsChange`; `/standup` renders a live approval tray (status/validation badges, Approve/Reject via `DisabledWithTooltip`, Summarize button), replacing the old static preview tray. Header shows `approver`/`read-only` badge.

**Verification.** `cd web && npm run build` clean (only pre-existing chunk warning). `python3 -m py_compile web/*.py scripts/smoke_standup_ws.py` OK. Rebuilt web container. `scripts/smoke_standup_ws.py` rewritten to authenticate two clients via Basic Auth seeded POC users and assert the full gated path — green: two-client join/chat + extraction, dry-run summarize persistence, **viewer approve → forbidden**, **admin approve → approved (actor recorded, applied=false)**, snapshot persistence. Also confirmed: snapshot 401-without-auth / 200-with-auth, unauthenticated ws connect rejected with 1008. `scripts/smoke_auth.sh` no regression (83/0/3). No new env vars (reused `STANDUP_DRY_RUN_ONLY`). Note: verification used POC password `changeme-poc` against `perm/auth/users.json` (gitignored).

**Files:** `web/auth.py`, `web/standup_ws.py`, `web/standup_store.py`, `web/src/components/auth-provider.tsx`, `web/src/components/standup-chat.tsx`, `web/src/routes/standup.tsx`, `scripts/smoke_standup_ws.py`, `docs/standup.md`, `IMPLEMENT.md`, `progress.md`.

## Session 2026-05-22 (pi agent) — S19 auth login hotfix

User reported web GUI login not working. Root cause had two parts:

1. **`perm/auth/users.json` missing** — the auth seed script (`web/auth_seed.py`) had never been run, so `/data/auth/users.json` didn't exist inside the container. Web logs showed `auth: users file not found: /data/auth/users.json` on every request.
2. **`auth_seed.py` not in Docker image** — `web/Dockerfile` only copied `main.py` and `auth.py`, but `auth.py` does `from auth_seed import verify_password` at runtime, causing `ModuleNotFoundError: No module named 'auth_seed'` on every login attempt (HTTP 500).

**Fix:**
- Ran `AUTH_BASIC_SEED_PASSWORD=changeme-poc AUTH_BASIC_USERS_FILE=./perm/auth/users.json python3 web/auth_seed.py` to generate the missing user credentials file (6 seeded users).
- Added `auth_seed.py` to the Dockerfile COPY line: `COPY main.py auth.py auth_seed.py ./`
- Rebuilt & restarted web container: `docker compose up --build -d web`
- Verified login works: `curl -u 'simone.patel@lanGarland.com:changeme-poc' http://localhost:5452/api/architecture` → 200

**Files changed:**
- `web/Dockerfile` — added `auth_seed.py` to COPY
- `perm/auth/users.json` — generated (gitignored, persisted via bind mount)

**Follow-up:** `AUTH_BASIC_SEED_PASSWORD` is currently unset in `.env`, so the seed script defaults to `changeme-poc` with a warning. Production deployments should set this to a real secret.

## Session 2026-05-22 (pi agent) — landing S13/S15/S19/S20 + worktree cleanup

Picked up handoff from previous multi-agent session. All co-mingled changes across S13, S15, S18, S19, S20 were disentangled and committed by stage.

**Commits landed (6):**
- `064af8d` feat(S15): ask_data deadline + batch notes + wrangler bulk projection + pipeline code view
- `fdd3c02` feat(S13): migrate hardcoded color literals to semantic tokens (6 components, ported from pi-stage13-15 worktree)
- `98850b3` feat(S19): web auth/RBAC — identity resolution, route guards, UI gating, actor audit
- `2a3e853` feat(S20): standup Jira cockpit — websocket chat, dry-run agent, session persistence
- `17553f3` docs: update IMPLEMENT.md + progress.md checkboxes
- `8ef52e8` docs: update COORDINATION.md

**S13 cleanup:** Ported 5 token-migration files from pi-stage13-15 worktree via direct copy (connection-bubble, hub-columns, relate-panel, workflow-stepper, hub). Workflow.tsx required surgical application — token changes only, preserving S19 auth gating (DisabledWithTooltip, useAuth).

**S19 audit.1 fix:** The parallel Claude agent's audit.1 task was incomplete — MCP-side functions accepted `actor` param but `web/main.py` never injected it. Fixed by: (1) guards store resolved user in `request.state.user`, (2) `_actor_from_request()` extracts it, (3) all 14 write endpoints now inject `actor` dict into MCP tool args.

**Worktree cleanup:**
- Removed 2 stale Claude worktrees (`.claude/worktrees/agent-*`) — content confirmed fully in main
- Removed pi-stage13-15 worktree + branch — S13 changes ported
- Removed 6 disposable subagent report files
- Pruned stale branch refs

**Build verification:** py_compile + npm run build both green. Merged to main and pushed.

## Session 2026-05-22 (docs-wiki agent) — S18/S19 doc tasks + Stage 5 shelved + coordination
- **S18.discovery.1 DONE** — `docs/architecture-inventory-template.md` (new): capture form for environments/accounts, AWS network detail (VPC/subnet/CIDR/SG), compute & data nodes (hostname/IP/instance_type/storage/retention/runbook_slug), integrations/edges (protocol/auth_mode/agentic_status), RISK→artifact flow checklist, and a known-unknowns table. All infra values `TBD`; field names align with the Stage-18 graph schema. Importable into the Docs Wiki.
- **S19.policy.1 DONE** — `docs/auth-rbac.md` (new): group→role→capability map, `/api/*` capability requirements (401 vs 403), SSO-prod / Basic-POC assumptions + all six `AUTH_MODE`s, seeded POC users, LDAP/auth-agent privacy boundary, and a non-blocking open-questions list.
- **Stage 5 (Copilot upstream) SHELVED** per user — `IMPLEMENT.md` header marked SHELVED + added to Out of scope; narrative retained for revival. Recorded in agent memory.
- **Coordination hardening** — `COORDINATION.md`: golden rule 7 (stage by name, never `git add -A`), new "IMPLEMENT.md commit protocol", and Incident 2 (commit `b171cd7` swept the S18/S19 checkbox flips). Both main-tree agents share branch `stage-14-docs-wiki`.
- Doc-only session; no code/build touched. Commits `5e7dd06` (docs) + `35a6e26` (coordination), cherry-picked to `main` this session.

## Stage 11 — Compliance command center: Overview page (DONE)
- **`overview_summary` MCP tool** (`mcp/overview.py`): reads `audit_findings`, `epics`, `work_items`, `pr_records` + the connector registry; evaluates six attention rules server-side (overdue, due_soon, prioritized, high_severity, blocked_pr, stalled); returns `{kpis, attention[], connectors[], tables{}, generated_at}` in one round-trip.
- **`GET /api/overview` proxy** (`web/main.py`): calls `overview_summary` via `_mcp_tool` + `_extract_json_block`.
- **Seed additions** (`mongo-seed/06-work_items.js`, `07-pr_records.js`, `13-due-dates.js`): due dates + staleness/check fixtures added so all attention rules have real data; applied via `scripts/reseed.sh`.
- **`useOverview()` query hook** (`web/src/lib/queries.ts`, `types.ts`): polls every 30 s; `placeholderData: (prev) => prev` prevents page blanking on refetch.
- **Overview SPA route** (`web/src/routes/overview.tsx`): 6 `StatCard` KPI row, full-width `AttentionPanel` (`web/src/components/attention-panel.tsx`), connector-health strip, 2×2 `MiniTable` grid (`web/src/components/mini-table.tsx`), retained activity trend.
- **Smoke test** (`scripts/smoke_overview.sh`): green — `/api/overview` returns all four sections; KPIs `{open_findings:4, active_epics:4, inflight_work_items:4, open_prs:2, connectors_healthy:1/8, attention:10}`; 10-item ranked attention list (overdue → due_soon → blocked_pr); `tools/list` returns 32 tools including `overview_summary`.
- **Env vars** (all optional, all defaulted): `OVERVIEW_DUE_SOON_DAYS=14`, `OVERVIEW_STALE_DAYS=7`, `OVERVIEW_ATTENTION_LIMIT=10`, `OVERVIEW_TABLE_ROWS=5`, `OVERVIEW_POLL_MS=30000`.

## Stage 12 — Domain-rich connector data + cross-system topology (DONE)
- **Mock data** (`S12.mock.*`, `S12.field.*`): every connector's `summary()` now returns a `schema` hint + domain-shaped `sample_data`:
  - AWS — multi-service inventory (RDS/S3/CloudTrail/KMS/ELB/IAM) with account/region/resource-id/service/status; one prod RDS row has `audit_logging:"disabled"` (a weak-spot).
  - Jira — active sprint + canonical issue fields (`fields.*`) grouped by epic; flagged/neglected tickets.
  - ServiceNow — canonical `incident` + `change_request` tables (impact/urgency/priority, cmdb_ci, sla_due, cab_required, etc.); P1 incident + high-risk change.
  - GitHub — commits per project auto-tagged to epics + `checks_state` (one failing).
  - Confluence — related articles with canonical content shape + `matched_on` relatedness.
  - Snowflake/MongoDB/Archer — schema hints + filled-out rows.
- **Topology** (`S12.topo.*`): `mcp/topology.py` builds `{nodes,edges,concerns,zones}`; `topology_graph` MCP tool + `GET /api/topology` proxy. 8 nodes / 11 edges / 6 ranked concerns.
- **Architecture page** (`S12.web.1/2`): new `/architecture` route (sidebar entry) — React Flow (`@xyflow/react`) interactive diagram, zoned layout, teal edges (red+animated for concerns), pan/zoom/minimap/controls, node tooltips, right-rail clickable concern list deep-linking to the Hub.
- **Hub** (`S12.web.3`): schema-keyed column registry (`web/src/components/hub-columns.tsx`) — AWS + ServiceNow now render (were empty), Jira sprint header + epic grouping, GitHub tags + checks badge, Confluence `matched_on` chips.
- **Persistence** (`S12.persist.1`): Mongo moved to a host bind mount `./perm/db:/data/db` (named volume removed); `./perm/` gitignored; `scripts/reseed.sh` re-applies seeds (init scripts only run on first empty-dir init). **Proven**: a marker row survived `docker compose down && docker compose up --build -d`.

## Stage 13 — Fleet-Dispatch design system (DONE, one follow-up)
- `web/src/index.css` tokens remapped to brand palette: navy `#1A1446` canvas (dark = default/headline look), amber `#FFD000` primary, teal `#06748C` secondary, white text; charts lead amber+teal; destructive/success kept for meaning.
- Font → Roboto, self-hosted via `@fontsource/roboto` (offline-safe), imported in `main.tsx`.
- **Follow-up `S13.cleanup.1` (partial)**: status-color literals remain in `hub-columns.tsx`/`hub.tsx`/`workflow-stepper.tsx` by design (red/green semantics); fuller token migration of non-semantic blues/purples is open.

## Stage 14 — Docs Wiki + Confluence sync (COMPLETE)
- **Data model (S14.model.1, DONE)**: `mongo-seed/14-docs.js` seeds `docs`/`doc_revisions`/`doc_sync_log` (incl. one deliberately-stale doc to exercise lifecycle). `mcp/db.py` gained docs system-of-record helpers — `docs_list/get/upsert/set_flags/search`, `doc_sync_log_append/recent`, `docs_set_confluence_id` — all auditing via `_audit(source="docs_*")`. Flags validated against the 14b enums (`status` ∈ up_to_date/needs_attention/archivable/archived; `visibility` ∈ internal/public).
- **CRUD tools (S14.api.1, DONE)**: `mcp/docs.py` adds path-grouped tree building + `derive_status` lifecycle (needs_attention when stale > `DOCS_REVIEW_DAYS`; archivable when stale AND unreferenced). `mcp/server.py` registers + dispatches 7 tools (`docs_list/get/upsert/set_flags/search/sync/agent_run`). Verified: upsert v1→v3 with revisions preserved + audit row written.
- **Confluence sync (S14.sync.1, DONE — dry-run)**: `mcp/docs_sync.py` maps `path`→Confluence ancestor pages, pushes public docs idempotently (stores `confluence_page_id`, updates in place after), `tags[]`→labels, logs every action to `doc_sync_log`. Connector gained `confluence_update_page` + create now returns a deterministic page id. Dry-run by default; live only when `DOCS_SYNC_ENABLED` + `CONN_CONFLUENCE_ENABLED` + `WORKFLOW_WRITES_ENABLED`. Verified plan mirrors `runbooks/` into space `COMP`, no outbound calls.
- **Agent (S14.agent.1, DONE & verified live)**: `mcp/docs_agent.py` is a checkpointed LangGraph `StateGraph` — `do_reconcile → do_triage → do_suggest → apply_gate (interrupt) → apply_approved → END`, compiled with `MemorySaver` keyed by `thread_id`. A fresh run pauses at the gate (`status="waiting_approval"`, returns `run_id` + proposals); resuming with `{run_id, resume_decision}` (slugs / `"all"` / `"reject"`) applies only approved proposals via an audited `docs_upsert` (`source="docs_agent_apply"`). The `/docs` Agent panel renders the gate (per-proposal checkboxes + Apply selected / Apply all / Reject). Verified live: fresh→waiting_approval; resume `reject`→completed, no writes; resume `all` on a seeded `needs_attention` doc → v1→v2, status→`up_to_date`, new audited revision. (Gotcha: LangGraph 0.2.62 rejects a node name equal to a state-key name — nodes are `do_*`.)
- **Smoke (S14.verify.1, backend DONE)**: `scripts/smoke_docs.sh` is green — tools registered, CRUD+revision+audit, flag transitions, dry-run sync plan mirrors tree, agent emits proposals without applying.
- **Env (defaulted, sync off)**: `DOCS_REVIEW_DAYS=90`, `DOCS_CONFLUENCE_SPACE=COMP`, `DOCS_SYNC_ENABLED=false`, `DOCS_DEFAULT_VISIBILITY=internal` — added to `.env.example` + `.env.local`.
- **Migration + web (S14.migrate.1/S14.web.1/S14.web.2, DONE)**: `scripts/import_docs.py` imports the repo `.md` corpus as v1 wiki docs; `/api/docs*` proxies and typed hooks landed; `/docs` SPA route provides tree, Markdown view, editor/preview, flag/tag controls, search, sync and agent actions, plus review queue.

## Stage 15 — Operational fixes & UX quick-wins (partial)
- **S15.wrangler.2 COMPLETE**: `/wrangler` now has an XL-screen MongoDB aggregation JS panel that renders `db.<collection>.aggregate([...])`, updates after successful preview/run/save/load, preserves the last successful pipeline when visual edits are invalid or untested, and supports copy-to-clipboard for the full pipeline and each individual stage snippet. Verified with `cd web && npm run build`.
- Still open: `S15.wrangler.1` bulk projection actions and `S15.askdata.1` timeout/empty-response fix.

## Stage 17 — Builder model upgrade to APEX + per-role `max_tokens` (COMPLETE)
- Builder subagent now runs on `Qwen3.6-35B-A3B-APEX-MTP-I-Balanced` (port 9292) with 60k `max_tokens`.
- Agent endpoint retains `qwen3.6-27b` as default upstream model.
- Fixed: agent omits `tools` field when empty (upstream vLLM rejects `tools: []`).
- New `llm_max_tokens(role)` helper in `mcp/llm.py` for per-role token budgets.
- Verified: agent plain chat, tool dispatch (echo, summarize_text), builder math, builder code gen.

## Verified live (rebuilt stack)
- `/api/topology` → 8 nodes, 11 edges, 6 concerns (prod RDS logging disabled, P1 incident, 2 neglected tickets, failing checks, high-risk change).
- `/api/connectors` → schema + non-empty sample_data for all connectors.
- `/architecture` → HTTP 200; web `/healthz` ok; all containers healthy.
- Persistence survives `down && up --build`.

## Key files changed / committed this session
- `IMPLEMENT.md` — archived completed sections; added/updated roadmap stages **18** (architecture diagram v2), **19** (SSO/Basic Auth + LDAP RBAC), **20** (Standup Jira cockpit), **21** (Deep Agent platform); env surface updated.
- `IMPLEMENT-ARCHIVE.md`, `COORDINATION.md` — archive + multi-agent coordination rules.
- `mcp/docs_agent.py`, `mcp/server.py` — Stage 14 docs-agent converted to checkpointed LangGraph HITL apply gate and exposed via MCP.
- `web/main.py`, `web/src/lib/{queries,types}.ts`, `web/src/routes/docs.tsx` — Docs Wiki web proxies/hooks/UI plus docs-agent apply/reject controls.
- `mcp/db.py`, `web/src/routes/sheet.tsx` — Stage 6 followups: accurate row counts, NL column reactivity, boolean/string-array editors.
- `caddy/Caddyfile.snippet.example`, `docs/clients.md`, `mcp/server.py` — Stage 3 SSE framing and optional Caddy MCP snippet.
- `scripts/import_docs.py` — Stage 14 markdown corpus importer.
- `web/src/routes/wrangler.tsx` — Stage 15 live MongoDB aggregation JS panel + copy actions.

## Session 2026-05-22 (Stage 20 standup orchestration) — YOLO vertical slice
- **S20.policy.1 DONE** — `docs/standup.md` documents roles (session owner/scrum-master/product owner, participant, observer, admin fallback), dry-run policy, `STANDUP_DRY_RUN_ONLY` / `JIRA_WRITES_ENABLED` interaction, and current limitations.
- **S20.ui.1 / S20.explorer.1 DONE** — `/standup` route added with sidebar navigation; Jira Explorer is the dominant panel, reusing `JiraEditableGrid`; `allowApply={false}` disables apply from Standup until approval/RBAC lands while Hub keeps normal Stage-16 behavior.
- **S20.chat.1 DONE (initial live slice)** — `StandupChat` connects to `/api/standup/ws/daily-standup`, handles snapshot/chat/presence/error events, retries/falls back to local capture, highlights URLs/Jira keys/@mentions, and reports association count to the configuration panel.
- **S20.links.1 DONE** — link/mention/Jira-key extraction in both MCP helper (`mcp/standup_agent.py`) and web websocket store (`web/standup_store.py`) for Jira, Confluence, GitHub, ServiceNow/SNOW, Archer, Snowflake, MongoDB, generic URLs, and @mentions.
- **S20.agent.1 DONE (dry-run helper)** — MCP tools `standup_link_context` and `standup_summarize` registered; outputs stay `proposed`/`dry_run`, never stage Jira or mutate external systems; unsupported planner models fail fast.
- **S20.model.1 / S20.ws.1 DONE (web-owned JSON persistence)** — `web/standup_store.py` stores sessions/messages/proposals/agent_runs in `STANDUP_STORE_PATH`, `/data/auth/standup_sessions.json` when mounted, or `/tmp/sglandsimple_standup_sessions.json` for local dev; `web/standup_ws.py` exposes snapshot + websocket fanout for join/chat/typing/placeholder summarize/approve/reject.
- **S20.verify.1 PARTIAL** — `scripts/smoke_standup_ws.py` added for two-client websocket smoke. Direct store smoke passed; full websocket smoke requires rebuilt/running web container.

## Audit findings 2026-05-22 (parallel-agent diff audit)
- Created `docs/parallel-agent-diff-audit.md` documenting dirty tracked/untracked files, stale worktrees, and recommended handling order.
- See `COORDINATION.md` for commit protocol; current tree has co-mingled S15/S19/S20/S22 changes pending explicit staging by path.

## Next agent — start here
1. **Read `COORDINATION.md` first** — respect file ownership, especially shared files (`IMPLEMENT.md`, `web/main.py`, `mcp/server.py`, `mcp/db.py`, `web/src/lib/{queries,types}.ts`).
2. **Stage 14 — COMPLETE.** All `S14.*` done incl. the docs-agent LangGraph apply-gate; eligible for archival to `IMPLEMENT-ARCHIVE.md` on the next pass.
3. **`progress.md` was restored** after being overwritten by an S20 subagent. Older Stage 11-17 history is preserved above; newer S20 notes are appended below.
4. `S13.cleanup.1` — finish migrating non-semantic color literals to tokens.
5. `S15.*` — wrangler bulk projection (`S15.wrangler.1`) and ask_data timeout fixes (`S15.askdata.1`), per `IMPLEMENT.md` ownership map. `S15.wrangler.2` is complete.
6. **Stage 18–22** — architecture diagram v2 (partially done), web auth/RBAC (in progress), Standup Jira cockpit (vertical slice done, needs landing), UX/chat polish + Wrangler derived fields — see `IMPLEMENT.md` and `docs/parallel-agent-diff-audit.md`.

## Session 2026-05-22 (pi agent) — S19 logout button + credential cache fix

User reported that login persisted even in a new incognito browser — no way to sign out.

**Root cause:** HTTP Basic Auth browsers cache credentials per-origin. There is no JavaScript API to clear them. The only reliable way is to force a 401 response with `WWW-Authenticate`, which causes the browser to forget its cached credentials.

**Changes:**

1. **`web/main.py`** — Added `POST /api/logout` endpoint that raises HTTP 401 with `WWW-Authenticate: Basic realm="sglandsimple"` (Basic Auth mode) or plain 401 (other modes). This forces the browser to clear its credential cache for the origin.

2. **`web/src/lib/queries.ts`** — Added `useLogout()` mutation that:
   - Calls `fetch("/api/logout", { method: "POST" })` (raw fetch, not `api.post`, because the 401 is intentional)
   - Swallows the expected 401 error
   - Clears all React Query cache via `qc.clear()`
   - Hard-navigates to `/` to trigger the browser's native login prompt

3. **`web/src/components/topbar.tsx`** — Added `LogOut` icon button next to the authenticated display name. Calls `logout.mutate()` on click. Disabled while logout is in progress.

**Files changed:**
- `web/main.py` — `POST /api/logout` endpoint
- `web/src/lib/queries.ts` — `useLogout()` hook
- `web/src/components/topbar.tsx` — logout button
- `IMPLEMENT.md` — S19.logout.1 task added + checked
- `COORDINATION.md` — S19 status updated

**Verification:**
- `python3 -m py_compile web/main.py` — passes
- `cd web && npm run build` — passes (tsc + vite, clean)

## Session 2026-05-22 (S20.agent.2 subagent) — standup agent template/docs context
- **S20.agent.2 DONE** — `mcp/standup_agent.py` now builds deterministic story template context for `standup_summarize`: Stage-9 Jira story template shape, acceptance-criteria format, default standup labels, priority/story-point guidance, selected epic/issue context, Docs Wiki docs, and Confluence links.
- New `new_jira_work` proposals remain dry-run/proposed and are normalized with `summary`, `description`, `issue_type`, `acceptance_criteria`, `labels`, `priority`, `story_points`, `epic_link`, `doc_links`, `related_links`, and `source_message_ids` defaults when missing.
- `docs/standup.md` documents the template/context behavior.
- Validation: `python3 -m py_compile mcp/standup_agent.py` passed. An optional direct Python import smoke could not run in the host environment because `langchain_openai` is not installed outside the container/venv.

## Session 2026-05-22 (S20.identity.1 subagent) — standup auth identity wiring
- **S20.identity.1 DONE** — Standup chat now uses Stage-19 `/api/me` identity via `useAuth()` for display name/email, sends `display_name` + `email` on websocket `join` and `chat.message`, and falls back to the existing Browser suffix when no authenticated user is available.
- Backend websocket identity resolution now calls `auth.resolve_user(websocket)` where possible, tracks `ClientState.email`, keeps legacy header/query/payload fallback for disabled/no-user cases, includes `display_name`/`email` in presence, and persists `author_email` on standup messages.
- Validation: `python3 -m py_compile web/standup_ws.py web/standup_store.py web/main.py` and `cd web && npm run build` passed.

## Session 2026-05-22 (S20.trace.1 subagent) — standup trace bubble UI
- **S20.trace.1 UI DONE** — `/standup` Jira Configuration / tool trace stays collapsed by default and expands into dry-run/live-write gates, connector health, websocket/presence/message trace, dry-run agent/tool placeholders, and cross-service association details.
- `StandupChat` now emits association metadata and trace telemetry to the parent route without backend changes.
- Validation: `cd web && npm run build` passed (Vite chunk-size warning only).

## Session 2026-05-22 (S20.proposals.1 subagent) — standup proposal persistence + dry-run Jira staging
- **S20.proposals.1 DONE** — websocket `agent.summarize` now calls MCP `standup_summarize`, persists an `agent_run`, and stores returned proposals as JSON-backed `standup_proposals` with `status=proposed`, `dry_run=true`, `dry_run_payload`, `validation_state`, source message IDs, rationale, actor, and timestamps.
- `new_jira_work` proposals are retained as dry-run standup proposals pending HITL approval/apply. `jira_edit` proposals with `edits[]` or `issue_key`/`changes` are staged through existing Stage-16 `jira_stage_edits` and immediately validated with `jira_validate_staged`; no `jira_apply_staged` call or live external write occurs.
- Websocket broadcasts `agent.running`, `agent.summary`, `proposal.created`, and `proposal.updated`; unsupported/unavailable agent calls degrade to a persisted dry-run placeholder instead of losing the request.
- **S20.verify.1 backend smoke expanded (partial)** — `scripts/smoke_standup_ws.py` now triggers `agent.summarize`, asserts the proposed/dry-run shape including `validation_state`, and verifies proposal persistence through the snapshot endpoint. Full approval/RBAC/live container smoke remains for later.
- Validation: `python3 -m py_compile web/standup_store.py web/standup_ws.py scripts/smoke_standup_ws.py` passed.

## Session 2026-05-22 (pi orchestrator) — coordination cleanup + integrated verification pass
- Re-read and updated `COORDINATION.md`; future edits stayed scoped to Stage 19 admin diagnostics and Stage 20 standup sections. No broad staging planned; commit must stage named paths only.
- **S19.admin.1 DONE** — `/api/auth/diagnostics` is guarded by `canAdminAuth`; `/auth-admin` renders auth mode, group/role/capability mappings, cache status, LDAP adapter status, seeded POC identity hints, and recent denial reasons. Fixed Badge variants to match the project design-system API and updated `web/Dockerfile` so `auth_ldap.py`/`auth_explain.py` are present in the runtime image.
- Stage 20 docs/checklists reconciled to actual implementation: identity, agent template context, proposal persistence/staging, and trace bubble are complete; approval/RBAC/full rebuilt-stack verification remain open.
- Validation: `python3 -m py_compile mcp/*.py web/*.py scripts/*.py` passed; `cd web && npm run build` passed after fixing `/auth-admin` badge variants; rebuilt/restarted web with `docker compose up --build -d mcp web`; regenerated POC Basic users with `AUTH_BASIC_SEED_PASSWORD=changeme-poc AUTH_BASIC_USERS_FILE=./perm/auth/users.json python3 web/auth_seed.py`; `bash scripts/smoke_auth.sh` passed (83 pass / 0 fail / 3 skipped mode-specific checks); `scripts/smoke_standup_ws.py` passed; `/api/auth/diagnostics` smoke passed for admin user.

## Session 2026-05-26 — Stage 21 YOLO runtime/UI pass
- **S21.runtime.1 DONE** — Deep Agent `agent_run_start` now persists a `running` record and launches orchestrator execution in a background task, so API callers receive a pollable `run_id` immediately instead of blocking behind long LLM/subagent hops. Existing status/resume/cancel/artifacts persistence remains in `deep_agent_runs`.
- Added web `/api/agents/*` proxies for profile list, run start/status/resume/cancel/artifacts with actor propagation from Stage-19 auth where applicable.
- Added typed TS runtime models and React Query hooks for Deep Agent profiles/runs/artifacts.
- **S21.ui.1 DONE** — new canRunWorkflow-gated `/agents` operations page + sidebar item: profile roster, dry-run start form, polling status, result/error/artifact inspection, pending approval approve/reject controls, and cancel action.
- Updated `IMPLEMENT.md` and `CHANGELOG.md` for observable Stage-21 runtime/UI behavior.
- Validation: `python3 -m py_compile mcp/deep_agent/runtime.py web/main.py` passed; `cd web && npm run build` passed (Vite chunk-size warning only).

## Session 2026-05-26 — Stage 30 cross-agent git hook
- **S30.git-hook.1 DONE** — added tracked `scripts/git-hooks/pre-commit` plus `scripts/install-git-hooks.sh`. Installing sets `core.hooksPath=scripts/git-hooks`, so the same commit-time guard applies to Claude Code, PiAgent, and humans in that clone/worktree.
- The hook checks staged Python files with `python3 -m py_compile` and staged `web/**/*.ts(x)` with `cd web && npx tsc -b --noEmit` when `web/node_modules` exists. It is a no-op when no relevant files are staged and prints the emergency `git commit --no-verify` bypass message on failure.
- Documented in `COORDINATION.md` that **both Claude Code and PiAgent must observe the rules**; Claude's local `.claude/` hook is only the early layer, while the tracked git hook is the cross-agent backstop.
- Validation: `bash scripts/install-git-hooks.sh` set `core.hooksPath` to `scripts/git-hooks`; `bash -n scripts/git-hooks/pre-commit scripts/install-git-hooks.sh` passed; `cd web && npx tsc -b --noEmit` passed.
