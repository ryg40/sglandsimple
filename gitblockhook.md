# gitblockhook.md — multi-agent git/worktree hygiene enforcement

**Purpose.** Stop the recurring collisions where a second agent edits the shared
main tree instead of its own worktree (COORDINATION.md rule 2) and where broad
`git add -A` / `git commit -a` sweeps another agent's unstaged edits into the
wrong commit (COORDINATION.md Incident 2). Prose hasn't held — this moves
enforcement to **mechanism**.

> **This repo is worked by TWO agents: a Claude Code session and a PiAgent
> session.** That dictates a two-layer design:
>
> | Layer | Lives in | Fires for | Catches |
> | --- | --- | --- | --- |
> | A. Claude Code hooks | `.claude/` (**gitignored — local only**) | Claude Code only | this agent, early, with context injection |
> | B. Shared git hook | `scripts/git-hooks/` (**tracked**) via `core.hooksPath` | **any** committer incl. PiAgent | both agents, at commit time |
>
> Claude Code hooks in `.claude/settings.json` **will not** intercept PiAgent —
> and `.claude/` is gitignored here (see `.gitignore:15`), so it can't be shared
> through git anyway. **PiAgent must wire its own equivalent of Layer A** (a
> pre-tool/command guard that denies the broad git forms + injects the rules at
> session start). The git hook (Layer B) is the cross-agent backstop that binds
> PiAgent regardless. Nothing here touches PLANTMUX tmux pane management.

Everything needed is inlined below. Create the files at the indicated paths,
`chmod +x` the scripts, and run the one install command for Layer B.

---

## Layer A — Claude Code hooks (local, this agent)

### `.claude/settings.json`
Additive `hooks` block. Do **not** clobber the existing permissions-only
`.claude/settings.local.json`.

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|resume|clear",
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/session-start.sh",
            "timeout": 10
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/block-broad-git.sh",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

### `.claude/hooks/block-broad-git.sh`  (`chmod +x`)
`PreToolUse(Bash)` guard. Receives the PreToolUse JSON on stdin; the command is
at `.tool_input.command`. Denies via
`hookSpecificOutput.permissionDecision:"deny"` (exit 0). Legitimate
`git add <path>` / `git commit -m` pass through untouched.

```bash
#!/usr/bin/env bash
# PreToolUse(Bash) guard — deny broad git staging/commit forms.
set -euo pipefail

input="$(cat)"

if command -v jq >/dev/null 2>&1; then
  cmd="$(printf '%s' "$input" | jq -r '.tool_input.command // empty')"
else
  cmd="$(printf '%s' "$input" | grep -oE '"command"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed -E 's/.*:[[:space:]]*"(.*)"/\1/')"
fi

# Dangerous broad forms only:
#   git add -A / --all / .        (sweeps everything, incl. other agents' WIP)
#   git commit -a / -am / --all   (auto-stages all tracked modifications)
if printf '%s' "$cmd" | grep -qE '(^|[;&|[:space:]])git[[:space:]]+add[[:space:]]+(-A\b|--all\b|\.([[:space:]]|$))' \
   || printf '%s' "$cmd" | grep -qE '(^|[;&|[:space:]])git[[:space:]]+commit[[:space:]]+([^;&|]*[[:space:]])?(-a\b|-am\b|--all\b|-[a-zA-Z]*a[a-zA-Z]*\b)'; then
  reason="Blocked broad git staging/commit ('${cmd}'). Another agent (Claude Code or PiAgent) may have unstaged edits in this shared tree — 'git add -A/./--all' and 'git commit -a/-am' sweep them into your commit (COORDINATION.md Incident 2). Stage explicit paths instead: git add path/to/your/file ... then git commit -m '...'. Run 'git status --short' and 'git diff --cached --stat' before committing."
  if command -v jq >/dev/null 2>&1; then
    jq -n --arg r "$reason" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}'
  else
    printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":%s}}\n' "\"${reason//\"/\\\"}\""
  fi
  exit 0
fi

exit 0
```

### `.claude/hooks/session-start.sh`  (`chmod +x`)
`SessionStart` guard. Injects the rules via `additionalContext`. SessionStart
cannot block a session, only add context.

```bash
#!/usr/bin/env bash
# SessionStart guard — inject multi-agent hygiene rules into context.
set -euo pipefail
cat >/dev/null  # consume stdin

ctx="Multi-agent hygiene (this repo is worked by a Claude Code session AND a separate PiAgent session — see COORDINATION.md):
- Before editing files another agent may touch (IMPLEMENT.md, mcp/server.py, web/main.py, web/src/lib/{types,queries}.ts, etc.), work in your OWN git worktree branched from HEAD: git worktree add ../wt-<name> -b <branch> HEAD. Do not edit the main tree if another agent owns it.
- Stage by explicit path. NEVER 'git add -A' / 'git add .' / 'git commit -a'/'-am' — a PreToolUse hook will deny these because they sweep the other agent's unstaged edits into your commit.
- Before committing: run 'git log --oneline -1' (did HEAD move?), 'git status --short', and 'git diff --cached --stat'; confirm every staged path is yours.
- A shared pre-commit hook (core.hooksPath) syntax-checks staged files; don't bypass it with --no-verify unless it's a real emergency."

if command -v jq >/dev/null 2>&1; then
  jq -n --arg c "$ctx" '{hookSpecificOutput:{hookEventName:"SessionStart",additionalContext:$c}}'
else
  esc="${ctx//\\/\\\\}"; esc="${esc//\"/\\\"}"; esc="${esc//$'\n'/\\n}"
  printf '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"%s"}}\n' "$esc"
fi
exit 0
```

### Verify Layer A
```bash
chmod +x .claude/hooks/*.sh
bash -n .claude/hooks/block-broad-git.sh
# DENY cases:
for c in "git add -A" "git add ." "git add --all" "git commit -am x" "git commit -a"; do
  printf '%s -> ' "$c"; echo "{\"tool_input\":{\"command\":\"$c\"}}" | .claude/hooks/block-broad-git.sh | jq -r '.hookSpecificOutput.permissionDecision'
done   # all -> deny
# ALLOW cases (exit 0, no JSON):
for c in "git add web/x.tsx" "git commit -m msg" "git status --short"; do
  printf '%s -> ' "$c"; echo "{\"tool_input\":{\"command\":\"$c\"}}" | .claude/hooks/block-broad-git.sh; echo "rc=$?"
done   # all -> rc=0, empty
```

---

## Layer B — shared `pre-commit` git hook (binds PiAgent too)

Tracked + shared via `core.hooksPath`, so it runs for **any** commit in this
repo no matter which agent makes it. Refuses a commit when a staged file fails a
cheap syntax check — this is what would have caught the broken
`chat-assistant.tsx` before it landed.

### `scripts/git-hooks/pre-commit`  (`chmod +x`)
```bash
#!/usr/bin/env bash
# Shared pre-commit syntax guard (S30.git-hook.1). Runs for any committer
# (Claude Code, PiAgent, human). Skip in a true emergency with: git commit --no-verify
set -euo pipefail
repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

# Staged (added/copied/modified) files only.
mapfile -t staged < <(git diff --cached --name-only --diff-filter=ACM)
[ ${#staged[@]} -eq 0 ] && exit 0

fail=0

# Python: py_compile each staged .py
for f in "${staged[@]}"; do
  case "$f" in
    *.py)
      if [ -f "$f" ] && ! python3 -m py_compile "$f" 2>/tmp/pchk.$$; then
        echo "pre-commit: python syntax error in staged file: $f" >&2
        sed 's/^/    /' /tmp/pchk.$$ >&2 || true
        fail=1
      fi
      ;;
  esac
done
rm -f /tmp/pchk.$$ 2>/dev/null || true

# Web TS/TSX: if any staged, run a scoped type-check (tsc -b is ~3s here).
if printf '%s\n' "${staged[@]}" | grep -qE '^web/.*\.(ts|tsx)$'; then
  if [ -d web/node_modules ]; then
    echo "pre-commit: type-checking web (tsc -b --noEmit)…" >&2
    if ! ( cd web && npx tsc -b --noEmit ) 2>/tmp/tschk.$$; then
      echo "pre-commit: TypeScript errors in web/ — fix before committing:" >&2
      sed 's/^/    /' /tmp/tschk.$$ >&2 || true
      fail=1
    fi
    rm -f /tmp/tschk.$$ 2>/dev/null || true
  else
    echo "pre-commit: web/node_modules missing; skipping tsc check" >&2
  fi
fi

if [ "$fail" -ne 0 ]; then
  echo "" >&2
  echo "pre-commit BLOCKED. Fix the staged files above, or bypass only in a real" >&2
  echo "emergency with: git commit --no-verify" >&2
  exit 1
fi
exit 0
```

### `scripts/install-git-hooks.sh`  (`chmod +x`) — one-time, per clone
```bash
#!/usr/bin/env bash
set -euo pipefail
repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"
chmod +x scripts/git-hooks/* 2>/dev/null || true
git config core.hooksPath scripts/git-hooks
echo "Installed: core.hooksPath -> scripts/git-hooks (pre-commit syntax guard active)"
```

### Install Layer B (each agent / clone runs once)
```bash
chmod +x scripts/git-hooks/pre-commit scripts/install-git-hooks.sh
bash scripts/install-git-hooks.sh
# verify:
git config --get core.hooksPath        # -> scripts/git-hooks
```

> `core.hooksPath` is **per-clone local config** (not committed), so each agent
> must run the installer once. The hook *script* is tracked, so once installed
> it is identical for everyone — that's what binds PiAgent.

---

## What PiAgent needs to build itself

`.claude/` is gitignored and Claude-Code-specific, so PiAgent can't use Layer A
as-is. PiAgent should:

1. **Install Layer B** (the shared git hook) — `bash scripts/install-git-hooks.sh`.
   This alone catches the "broken file committed" and stops broad-sweep damage
   from surviving past commit time for either agent.
2. **Mirror Layer A in PiAgent's own hook/guard system** — whatever PiAgent's
   equivalent of a pre-command/pre-tool hook is, port `block-broad-git.sh`'s
   regex to deny `git add -A|.|--all` and `git commit -a|-am|--all`, and inject
   the `session-start.sh` text as a session preamble. The deny logic is plain
   POSIX shell + a regex, so it's portable to any harness that can shell out.

---

## File manifest

| Path | Layer | Tracked? | chmod +x | Who installs |
| --- | --- | --- | --- | --- |
| `.claude/settings.json` | A | no (gitignored) | n/a | Claude Code |
| `.claude/hooks/block-broad-git.sh` | A | no (gitignored) | yes | Claude Code |
| `.claude/hooks/session-start.sh` | A | no (gitignored) | yes | Claude Code |
| `scripts/git-hooks/pre-commit` | B | **yes** | yes | both (`install-git-hooks.sh`) |
| `scripts/install-git-hooks.sh` | B | **yes** | yes | both, once per clone |
