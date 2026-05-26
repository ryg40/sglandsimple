#!/usr/bin/env bash
# Install tracked git hooks for this clone/worktree.
# Required for both Claude Code and PiAgent sessions in this repository.
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

if [ ! -d scripts/git-hooks ]; then
  echo "scripts/git-hooks not found" >&2
  exit 1
fi

chmod +x scripts/git-hooks/* 2>/dev/null || true
git config core.hooksPath scripts/git-hooks

echo "Installed: core.hooksPath -> scripts/git-hooks"
echo "Shared pre-commit syntax guard is active for this clone/worktree."
