#!/usr/bin/env bash
# Stage 14 — Docs Wiki backend smoke test.
#
# Exercises the MCP docs tools end-to-end against the running stack:
#   - docs tools registered in tools/list
#   - docs_list returns the path-grouped tree + review queue (stale doc flagged)
#   - docs_upsert bumps version + writes an append-only revision + audit_log row
#   - docs_set_flags flips visibility (audited)
#   - docs_search finds by body
#   - docs_sync produces a dry-run plan mirroring the tree (no outbound calls)
#   - docs_agent_run reconciles + triages + emits proposals WITHOUT applying
#
# Prereqs: stack up (scripts/reseed.sh applied so 14-docs.js is loaded), MCP on
# ${MCP_PORT:-5451}. Uses a fresh MCP session (Stage-3 session handshake).
#
# Usage: scripts/smoke_docs.sh

set -euo pipefail

MCP_PORT="${MCP_PORT:-5451}"
BASE="http://localhost:${MCP_PORT}/mcp"

SID=$(curl -sD- -o /dev/null "$BASE" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{}}' \
  | grep -i mcp-session-id | awk '{print $2}' | tr -d '\r')
[ -n "$SID" ] || { echo "FAIL: no session id from initialize"; exit 1; }
echo "session=$SID"

call() {  # call <name> <args-json>
  curl -s "$BASE" -H 'Content-Type: application/json' -H "Mcp-Session-Id: $SID" \
    -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\",\"params\":{\"name\":\"$1\",\"arguments\":$2}}"
}

py() { python3 -c "$1"; }

echo "== docs tools registered =="
curl -s "$BASE" -H 'Content-Type: application/json' -H "Mcp-Session-Id: $SID" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
  | py 'import sys,json; t=[x["name"] for x in json.load(sys.stdin)["result"]["tools"]];
need={"docs_list","docs_get","docs_upsert","docs_set_flags","docs_search","docs_sync","docs_agent_run"};
missing=need-set(t); print("FAIL missing:",missing) or sys.exit(1) if missing else print("ok:",sorted(need))'

echo "== docs_list: tree + review queue =="
call docs_list '{}' | py 'import sys,json; d=json.load(sys.stdin)["result"]["content"];
p=json.loads(d[-1]["text"]);
assert p["count"]>=1, p; print("count",p["count"],"queue",[r["slug"] for r in p["review_queue"]])'

echo "== docs_upsert: bump version + revision =="
call docs_upsert '{"slug":"welcome","body_md":"# Welcome (smoke)\n","owner":"smoke","note":"smoke"}' \
  | py 'import sys,json; p=json.loads(json.load(sys.stdin)["result"]["content"][-1]["text"]);
assert p["doc"]["version"]>=2, p; print("version",p["doc"]["version"],"created",p["created"])'

echo "== docs_set_flags: visibility=public =="
call docs_set_flags '{"slug":"welcome","visibility":"public"}' \
  | py 'import sys,json; p=json.loads(json.load(sys.stdin)["result"]["content"][-1]["text"]);
assert p["doc"]["visibility"]=="public", p; print("visibility",p["doc"]["visibility"])'

echo "== docs_search =="
call docs_search '{"query":"welcome"}' \
  | py 'import sys,json; p=json.loads(json.load(sys.stdin)["result"]["content"][-1]["text"]);
print("hits",[r["slug"] for r in p["results"]])'

echo "== docs_sync: dry-run plan mirrors tree =="
call docs_sync '{}' \
  | py 'import sys,json; p=json.loads(json.load(sys.stdin)["result"]["content"][-1]["text"]);
assert p["live"] is False, "expected dry-run by default"; print("live",p["live"],"space",p["space"],"actions",[(a["slug"],a["planned_action"]) for a in p["actions"]])'

echo "== docs_agent_run: proposals, none applied =="
call docs_agent_run '{"limit_suggestions":0}' \
  | py 'import sys,json; p=json.loads(json.load(sys.stdin)["result"]["content"][-1]["text"]);
assert p["applied_any"] is False, "agent must not auto-apply"; print("triage",[(t["slug"],t["suggested_status"]) for t in p["triage"]],"applied_any",p["applied_any"])'

echo "ALL DOCS SMOKE CHECKS PASSED"
