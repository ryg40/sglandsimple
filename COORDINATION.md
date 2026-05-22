# COORDINATION.md — multi-agent worktree & task hygiene

> Live coordination doc for when **more than one agent is working the IMPLEMENT.md backlog at the same time.** Read this before you touch files. It exists because two agents collided on shared files during the Stage-6/14 + Stage-13/15 parallel push (2026-05-22).

## Who is doing what (keep this current)

Update this table when you start/finish. One owner per stage.

| Stage(s) | Owner | Worktree / branch | Status |
| --- | --- | --- | --- |
| 6 followups, 14 (all incl. agent LangGraph apply-gate) | docs-wiki agent | `stage-14-docs-wiki` (main tree) | **COMPLETE** — built green + verified live (mcp/web rebuilt) |
| 13 (token cleanup), 15 (wrangler/ask_data) | stage13-15 agent | `/opt/stacks/sglandsimple-pi-stage13-15` [`pi-stage13-15`] | in progress |
| 3 (SSE transport, S3.transport.2/S3.expose.2) | current main-tree agent | main tree | landed; local SSE verified; manual external-client smoke pending |

## The golden rules

1. **One agent owns a file at a time.** Before editing a file, check the "File ownership map" below. If another stage already claims it, coordinate (additive-only, or hand off) — do not overwrite.
2. **Work in your own git worktree, branched from current `HEAD`.** Not from a stale commit. `git worktree add ../wt-myname -b my-branch HEAD`. (A worktree branched from an older commit will, on merge, *delete* everything added since — this already bit us; see "Postmortem".)
3. **Never copy a whole file across worktrees if it was branched from a different base.** Copy/port only the specific hunks you intentionally changed, or you'll silently revert another stage's work. Diff first (`diff -u main/file worktree/file`) and eyeball it.
4. **Land via additive edits, not wholesale file replacement,** for any file another agent might also touch (especially `web/main.py`, `mcp/server.py`, `mcp/db.py`, `web/src/lib/{types,queries}.ts`, `IMPLEMENT.md`).
5. **Build before you hand off.** `cd web && npm run build` (tsc + vite) and `python3 -m py_compile <changed .py>`. A green build in *your* worktree means nothing if you then copy stale files into main.
6. **Don't commit or push unless asked.** Leave changes in the working tree for review.

## File ownership map (current parallel work)

Shared/hot files — coordinate before editing:

| File | Touched by | How to share |
| --- | --- | --- |
| `IMPLEMENT.md` | everyone (checkbox flips + notes) | **Edit only your own stage's section.** Never rewrite the whole file. Append/flip your `S<n>.*` lines; leave others' lines alone. |
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
