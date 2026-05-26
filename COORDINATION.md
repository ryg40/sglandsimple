# COORDINATION.md — multi-agent worktree & task hygiene

> Live coordination doc for when **more than one agent is working the IMPLEMENT.md backlog at the same time.** Read this before you touch files. It exists because two agents collided on shared files during the Stage-6/14 + Stage-13/15 parallel push (2026-05-22).

## Who is doing what (keep this current)

Update this table when you start/finish. One owner per stage.

| Stage(s) | Owner | Worktree / branch | Status |
| --- | --- | --- | --- |
| 6 followups, 14 (all incl. agent LangGraph apply-gate) | docs-wiki agent | `stage-14-docs-wiki` (main tree) | **COMPLETE** — committed |
| 13 (token cleanup) | pi agent | main tree | **COMPLETE** — committed `fdd3c02` |
| 15 (wrangler bulk projection + code view, ask_data deadline) | pi agent | main tree | **COMPLETE** — committed `064af8d` |
| 3 (SSE transport) | docs-wiki agent | main tree | landed; manual external-client smoke pending |
| 18 (architecture diagram v2) | pi orchestrator | main tree | **COMPLETE** — export/docs/verify closed |
| 19 (web auth/RBAC) | pi agent | main tree | **COMPLETE** — auth/RBAC + admin diagnostics verified |
| 20 (standup Jira cockpit) | pi agent | main tree | **COMPLETE** — RBAC + HITL approval tray + websocket smoke verified |
| 22 (UX/chat polish + Wrangler derived fields) | pi agent | main tree | **COMPLETE** — chat.4 (newest-first feed), chat.5 (collapsed Ask Data query with <details>), chat.6 (slim dynamic banner) verified; py_compile + web build clean |
| 23 (Confluence wire-up + cross-system enrichment + teaching docs) | pi orchestrator + gpt-5.4 workers | main tree + isolated subagent worktrees | **COMPLETE** — Confluence live gate, overlap data, teaching docs, smoke verified |
| 24 (standup Epics + Templates reference rail) | pi agent | main tree | **COMPLETE** — `/standup` Epics/Templates cards landed, `standup_templates` MCP tool added, build/py-compile verified |
| 25 (standup production approvals viewport) | pi agent | main tree | **COMPLETE** — approver email gate, editable approvals viewport, Save/Submit flow, gated production apply path verified locally |
| 21 (Deep Agent platform) | pi agent | main tree | **IN PROGRESS** — DONE & on main: arch.1, upgrade.1 (LangChain 1.x), profile.1 (`profiles.yaml`+loader), context.1, orch.1 (`build_orchestrator`+allowlist). **runtime.1 PARTIAL** — 6 `agent_*` MCP tools live (`agent_profiles_list` verified; runs persist to Mongo) but `agent_run_start` hangs at `running` (orchestrator→`ask_data` CompiledSubAgent input contract + request timeout; needs background exec) and web `/api/agents/*` proxies not added. Next: finish runtime.1, then hitl.1. |
| 5 (Copilot upstream) | — | — | **SHELVED 2026-05-22** per user |

> **Single agent working the main tree.** The parallel agent sessions have completed. All work is committed on `stage-14-docs-wiki`. Follow the IMPLEMENT.md commit protocol below for any new edits.

> **⚠️ LangChain 1.x rebuild required (2026-05-26, S21.upgrade.1).** `main` now pins the MCP service to the LangChain 1.x line (`deepagents 0.6.3`, `langchain-core 1.4`, `langgraph 1.2`, `langchain-openai 1.2`, `openai 2.x`, `langgraph-checkpoint-mongodb 0.4`). After pulling, **rebuild the mcp image** (`docker compose build mcp && docker compose up -d mcp`) — a stale 0.3 image will fail. The Mongo checkpointer now uses the unified `MongoDBSaver` (its `from_conn_string` is a *sync* context manager). Default `docker compose up` is otherwise unchanged; the new `sandbox` runtime is opt-in (`docker compose --profile sandbox up -d`).

## The golden rules

1. **One agent owns a file at a time.** Before editing a file, check the "File ownership map" below. If another stage already claims it, coordinate (additive-only, or hand off) — do not overwrite.
2. **Work in your own git worktree, branched from current `HEAD`.** Not from a stale commit. `git worktree add ../wt-myname -b my-branch HEAD`. (A worktree branched from an older commit will, on merge, *delete* everything added since — this already bit us; see "Postmortem".)
3. **Never copy a whole file across worktrees if it was branched from a different base.** Copy/port only the specific hunks you intentionally changed, or you'll silently revert another stage's work. Diff first (`diff -u main/file worktree/file`) and eyeball it.
4. **Land via additive edits, not wholesale file replacement,** for any file another agent might also touch (especially `web/main.py`, `mcp/server.py`, `mcp/db.py`, `web/src/lib/{types,queries}.ts`, `IMPLEMENT.md`).
5. **Build before you hand off.** `cd web && npm run build` (tsc + vite) and `python3 -m py_compile <changed .py>`. A green build in *your* worktree means nothing if you then copy stale files into main.
6. **Don't commit or push unless asked.** Leave changes in the working tree for review.
7. **When you do commit, stage by name — never `git add -A`/`-a`/`.` while another agent is active.** Shared files (`IMPLEMENT.md` especially) get swept into the wrong commit otherwise. See "IMPLEMENT.md commit protocol" below.

## File ownership map (current parallel work)

Shared/hot files — coordinate before editing:

| File | Touched by | How to share |
| --- | --- | --- |
| `IMPLEMENT.md` | everyone (checkbox flips + notes) | **Edit only your own stage's section, and commit it on its own.** See the "IMPLEMENT.md commit protocol" below. Never rewrite the whole file. Append/flip your `S<n>.*` lines; leave others' lines alone. |
| `web/main.py` | S14 (docs proxies), S15 (`/api/ask_data` timeout) | Additive route blocks only. S14 added `/api/docs/*` before `api_download_report`; S15 edits the existing `/api/ask_data` handler. Disjoint — keep it that way. |
| `mcp/server.py` | S3 (SSE transport), S14 (docs tools, already landed) | Disjoint regions (transport/session vs. tool defs). Don't reformat unrelated areas. |
| `mcp/db.py` | S6 (`get_rows` count fix), S14 (docs helpers) | Both already landed in main; disjoint. Surgical edits only — do **not** copy a whole `db.py` from a pre-Stage-14 worktree (it drops the docs system-of-record helpers). |
| `web/src/lib/types.ts`, `web/src/lib/queries.ts` | S14 (docs types/hooks) | Pure appends at end of file. If S13/S15 need types, append yours below; don't touch existing exports. |
| `web/src/routes/wrangler.tsx` | S15 (bulk projection) | S15-owned. |
| `web/src/routes/chat.tsx` | S15 (ask_data error surfacing) | S15-owned. |
| `mcp/ask_data.py` | S15 (deadline/fan-out) | S15-owned. |
| `web/src/components/hub-columns.tsx`, `web/src/routes/hub.tsx`, `web/src/components/workflow-stepper.tsx` | S13 (token migration) | S13-owned. |
| `web/src/index.css` | S13 (already done) | S13-owned. |

Stage-14 / Stage-6 files now in main (don't revert): `mcp/db.py` (`get_rows` + docs helpers), `web/main.py` (docs routes), `web/src/{App.tsx,components/app-sidebar.tsx,lib/types.ts,lib/queries.ts,routes/sheet.tsx}`, `web/src/routes/docs.tsx` (new), `scripts/import_docs.py` (new).

## IMPLEMENT.md is now split

- `IMPLEMENT.md` — header + ground rules + **completed-stage summary table** + **open stages only** (3, 5, 6-followups, 13, 14, 15) + the Env-surface table.
- `IMPLEMENT-ARCHIVE.md` — full verbatim detail of completed stages (0–2, 4, 7–12, 16, 17). Read on demand; don't edit it for new work.

When flipping a checkbox: edit the open-stage section in `IMPLEMENT.md`. If you *complete a whole stage*, move its detail to `IMPLEMENT-ARCHIVE.md` and add a one-line row to the completed-stage table — but only when its tasks are all `[x]`.

## IMPLEMENT.md commit protocol (read this — it's where we keep colliding)

Both main-tree agents edit `IMPLEMENT.md`, and `git add -A` / `git commit -am` will **sweep another agent's unstaged checkbox flips into your commit**. That already happened on 2026-05-22: the stage13-15 agent's "Wrangler code view" commit (`b171cd7`) absorbed the docs-wiki agent's S18/S19 checkbox flips. No work was lost that time, but it scrambles attribution and risks committing half-finished edits from the other agent.

**Rules to prevent it:**

1. **Stage explicitly. Never `git add -A`, `git add .`, or `git commit -a`** while another agent is active. Name every path: `git add path/to/file1 path/to/file2`.
2. **Commit `IMPLEMENT.md` by itself, or only with files from your own stage.** Don't fold an `IMPLEMENT.md` flip into an unrelated feature commit unless every other change in that commit is yours.
3. **Before committing, run `git status --short` and `git diff --cached --stat`** and confirm *every* listed path is something you intended to touch. If you see another stage's file staged, unstage it (`git restore --staged <path>`).
4. **Check `git log --oneline -1` before you start a work session.** If HEAD moved since you last looked, the other agent committed; re-read your `IMPLEMENT.md` section before editing so you're flipping lines on the current text, not stale text.
5. **Untracked new files are safe from `-a` but not from `-A`.** New docs/scripts you create won't be swept by `git commit -am`, but *will* be by `git add -A`. This is the other reason to stage by name.

### Instructions specifically for the stage13-15 agent

- You own S13 (token cleanup) and S15 (wrangler/ask_data). Keep your `IMPLEMENT.md` edits to the **S13 and S15 sections only**.
- When you commit wrangler/ask_data code, **stage only your files** (`web/src/routes/wrangler.tsx`, `web/src/routes/chat.tsx`, `mcp/ask_data.py`, `web/main.py` ask_data hunk, etc.) **plus your own S13/S15 lines in `IMPLEMENT.md`** — by name, not `-A`.
- The docs-wiki agent's S18/S19 work is **doc-only** (`docs/architecture-inventory-template.md`, `docs/auth-rbac.md`) and already committed (`5e7dd06`). Don't touch those files or the Stage 18/19 sections.
- **Stage 5 is shelved** — skip it entirely.

## Verifying the integrated tree (do this before claiming done)

```bash
# from /opt/stacks/sglandsimple
python3 -m py_compile mcp/*.py web/main.py scripts/*.py
cd web && npm run build          # tsc -b && vite build — must be clean
```

For runtime checks, the smoke scripts target the running stack:
`scripts/smoke_docs.sh`, `scripts/smoke_sheet.sh`, `scripts/smoke_wrangler.sh`, `scripts/smoke_ask_data.sh`.

## Postmortem — what went wrong on 2026-05-22 (learn from it)

- Two subagents were spawned in auto-created worktrees that branched from `759fa8e` (one commit **behind** HEAD `0cf6485`, which carried the Stage-14 backend).
- One agent's worktree `mcp/db.py` therefore *lacked* the docs helpers. A naive `cp worktree/db.py main/db.py` would have deleted the entire Stage-14 system-of-record layer.
- Fix that worked: **diff every file before copying; copy only intended hunks; apply the one-line `get_rows` fix surgically to the up-to-date `db.py` instead of overwriting.**
- Lesson encoded in rules 2–4 above: branch from HEAD, never wholesale-copy across mismatched bases, prefer additive edits on shared files.

## Incident 2 — IMPLEMENT.md flips swept into the wrong commit (2026-05-22, later)

- The docs-wiki agent flipped S18.discovery.1 and S19.policy.1 to `[x]` in `IMPLEMENT.md` (uncommitted).
- The stage13-15 agent then committed its Wrangler code-view work with a broad `git add` and produced `b171cd7`, which **absorbed those S18/S19 flips** into a commit titled "add Wrangler aggregation pipeline code view."
- No work was lost (the flips were valid), but attribution was wrong and the docs-wiki agent's *new files* were left untracked, separated from their own checkbox flips.
- Fix/lesson encoded in rule 7 + the "IMPLEMENT.md commit protocol" section: **stage by name, commit `IMPLEMENT.md` on its own, and run `git diff --cached --stat` before committing** so you never carry another agent's unstaged edits.
