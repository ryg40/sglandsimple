#!/usr/bin/env bash
# Smoke test: Stage-16 HIL-gated Jira bulk editing.
#
# Round-trips stage -> validate -> apply(dry-run) -> revert against the
# running MCP server and asserts:
#   - staging produces a "staged" issue with a {from,to} diff
#   - validation marks a good edit "validated" and a bad edit "invalid"
#   - apply on a dry-run config returns apply_mode=dry_run with a plan and
#     mutates nothing live; an unvalidated row is refused
#   - audit_log grew across the lifecycle
#   - revert clears staged state
set -euo pipefail

MCP_URL="${MCP_URL:-http://localhost:5451/mcp}"
WEB_URL="${WEB_URL:-http://localhost:5452}"
MONGO_CONTAINER="${MONGO_CONTAINER:-sglandsimple-mongo}"
MONGO_USER="${MONGO_ROOT_USER:-root}"
MONGO_PASS="${MONGO_ROOT_PASSWORD:-rootpw}"
MONGO_DB="${MONGO_DB:-enterprise}"

# Two real sample issue keys from the connector's _SAMPLE.
GOOD_KEY="RDS-LOG-2"   # gets a valid edit
BAD_KEY="RDS-LOG-3"    # gets an invalid edit (priority=Wizard, empty summary)

say() { printf "\n===> %s\n" "$*"; }
fail() { printf "FAIL: %s\n" "$*"; exit 1; }

SID=$(curl -sS -i -X POST "$MCP_URL" \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{}}' \
  | grep -i mcp-session-id | awk '{print $2}' | tr -d '\r')
[[ -n "$SID" ]] || fail "no Mcp-Session-Id returned"
echo "Session: $SID"

mcp_call() {
  curl -sS --max-time 60 -X POST "$MCP_URL" \
    -H 'Content-Type: application/json' -H "mcp-session-id: $SID" -d "$1"
}
# JSON payload of a jira tool is in content[0].text
result_json() { echo "$1" | jq -r '.result.content[0].text'; }

audit_count() {
  docker exec "$MONGO_CONTAINER" mongosh --quiet \
    -u "$MONGO_USER" -p "$MONGO_PASS" --authenticationDatabase admin \
    "$MONGO_DB" --eval 'print(db.audit_log.countDocuments({source:/^jira_/}))' | tr -d '\r'
}

# Start clean: revert any leftover staged docs.
mcp_call '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"jira_revert_staged","arguments":{}}}' >/dev/null

before_audit=$(audit_count)
echo "jira audit rows before: $before_audit"

# ----- 1. list issues --------------------------------------------------------
say "jira_list_issues"
resp=$(mcp_call '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"jira_list_issues","arguments":{}}}')
echo "$resp" | jq -e '.result.isError == false' >/dev/null || fail "jira_list_issues error: $resp"
n=$(result_json "$resp" | jq '.issues | length')
[[ "$n" -ge 1 ]] || fail "expected >=1 issue, got $n"
echo "issues: $n"

# ----- 2. stage a good + a bad edit -----------------------------------------
say "jira_stage_edits (good=$GOOD_KEY priority->Critical, bad=$BAD_KEY priority=Wizard, summary='')"
stage=$(mcp_call "$(jq -nc --arg g "$GOOD_KEY" --arg b "$BAD_KEY" '{jsonrpc:"2.0",id:3,method:"tools/call",params:{name:"jira_stage_edits",arguments:{edits:[{issue_key:$g,changes:{priority:"Critical",story_points:8}},{issue_key:$b,changes:{priority:"Wizard",summary:""}}]}}}')")
echo "$stage" | jq -e '.result.isError == false' >/dev/null || fail "stage error: $stage"
staged_n=$(result_json "$stage" | jq '.staged | length')
[[ "$staged_n" -eq 2 ]] || fail "expected 2 staged, got $staged_n: $(result_json "$stage")"

# ----- 3. list shows staged overlay -----------------------------------------
say "jira_list_issues shows staged overlay"
resp=$(mcp_call '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"jira_list_issues","arguments":{}}}')
sc=$(result_json "$resp" | jq --arg g "$GOOD_KEY" '.issues[] | select(.key==$g) | ._stage_status')
echo "$sc" | grep -q staged || fail "good key not staged: $sc"

# ----- 4. validate -----------------------------------------------------------
say "jira_validate_staged"
val=$(mcp_call '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"jira_validate_staged","arguments":{}}}')
echo "$val" | jq -e '.result.isError == false' >/dev/null || fail "validate error: $val"
good_status=$(result_json "$val" | jq -r --arg g "$GOOD_KEY" '.results[] | select(.issue_key==$g) | .status')
bad_status=$(result_json "$val" | jq -r --arg b "$BAD_KEY" '.results[] | select(.issue_key==$b) | .status')
[[ "$good_status" == "validated" ]] || fail "good key not validated: $good_status"
[[ "$bad_status" == "invalid" ]] || fail "bad key not invalid: $bad_status"
echo "good=$good_status bad=$bad_status"

# ----- 5. apply (dry-run): only validated rows; bad row refused --------------
say "jira_apply_staged (expect dry-run plan)"
apply=$(mcp_call '{"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"jira_apply_staged","arguments":{}}}')
echo "$apply" | jq -e '.result.isError == false' >/dev/null || fail "apply error: $apply"
mode=$(result_json "$apply" | jq -r '.apply_mode')
[[ "$mode" == "dry_run" ]] || fail "expected dry_run (JIRA_WRITES_ENABLED should be false), got $mode"
applied_n=$(result_json "$apply" | jq '.applied | length')
plan_n=$(result_json "$apply" | jq '.plan | length')
skipped_bad=$(result_json "$apply" | jq -r --arg b "$BAD_KEY" '.skipped[] | select(.issue_key==$b) | .reason')
[[ "$applied_n" -eq 1 ]] || fail "expected 1 applied (good only), got $applied_n"
[[ "$plan_n" -eq 1 ]] || fail "expected 1 planned call, got $plan_n"
[[ -n "$skipped_bad" ]] || fail "bad/unvalidated key was not refused"
echo "mode=$mode applied=$applied_n plan=$plan_n; bad refused: $skipped_bad"

# ----- 6. audit grew ---------------------------------------------------------
after_audit=$(audit_count)
delta=$(( after_audit - before_audit ))
echo "jira audit rows after: $after_audit (delta=$delta)"
[[ "$delta" -ge 4 ]] || fail "expected jira audit_log to grow by >=4, got $delta"

# ----- 7. revert clears -------------------------------------------------------
say "jira_revert_staged"
rev=$(mcp_call '{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"jira_revert_staged","arguments":{}}}')
echo "$rev" | jq -e '.result.isError == false' >/dev/null || fail "revert error: $rev"
resp=$(mcp_call '{"jsonrpc":"2.0","id":8,"method":"tools/call","params":{"name":"jira_list_issues","arguments":{}}}')
staged_after=$(result_json "$resp" | jq '.staged_count')
[[ "$staged_after" -eq 0 ]] || fail "expected 0 staged after revert, got $staged_after"

# ----- 8. web proxy (best-effort) --------------------------------------------
if curl -sf -o /dev/null --max-time 5 "$WEB_URL/healthz"; then
  say "web /api/jira/issues"
  curl -sS "$WEB_URL/api/jira/issues" | jq -e '.issues | length >= 1' >/dev/null || fail "web /api/jira/issues"
fi

echo
echo "PASS — stage→validate→apply(dry-run)→revert round-trip; jira audit grew by $delta; no live write."
