#!/usr/bin/env bash
# Smoke test: exercise the Stage-6 sheet write surface end-to-end.
#
# Inserts a probe employee row, mutates a field, runs one sheet_apply_nl
# instruction targeting the probe, deletes the probe, and asserts that
# audit_log grew by the expected number of rows.
set -euo pipefail

MCP_URL="${MCP_URL:-http://localhost:5451/mcp}"
WEB_URL="${WEB_URL:-http://localhost:5452}"
MONGO_CONTAINER="${MONGO_CONTAINER:-sglandsimple-mongo}"
MONGO_USER="${MONGO_ROOT_USER:-root}"
MONGO_PASS="${MONGO_ROOT_PASSWORD:-rootpw}"
MONGO_DB="${MONGO_DB:-enterprise}"
PROBE_ID="emp-smoke-$(date +%s)"

say() { printf "\n===> %s\n" "$*"; }
fail() { printf "FAIL: %s\n" "$*"; exit 1; }

# ----- MCP session -----------------------------------------------------------
SID=$(curl -sS -i -X POST "$MCP_URL" \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{}}' \
  | grep -i mcp-session-id | awk '{print $2}' | tr -d '\r')
[[ -n "$SID" ]] || fail "no Mcp-Session-Id returned"
echo "Session: $SID"

mcp_call() {
  local body="$1"
  curl -sS --max-time 60 -X POST "$MCP_URL" \
    -H 'Content-Type: application/json' \
    -H "mcp-session-id: $SID" \
    -d "$body"
}

audit_count() {
  docker exec "$MONGO_CONTAINER" mongosh --quiet \
    -u "$MONGO_USER" -p "$MONGO_PASS" --authenticationDatabase admin \
    "$MONGO_DB" --eval 'print(db.audit_log.countDocuments({}))' \
    | tr -d '\r'
}

before_audit=$(audit_count)
echo "audit_log before: $before_audit"

# ----- 1. list collections ---------------------------------------------------
say "sheet_get_rows employees skip=0 limit=2"
resp=$(mcp_call "$(jq -nc --arg c employees '{jsonrpc:"2.0",id:1,method:"tools/call",params:{name:"sheet_get_rows",arguments:{collection:$c,skip:0,limit:2}}}')")
echo "$resp" | jq -e '.result.isError == false' >/dev/null || fail "sheet_get_rows error: $resp"

# ----- 2. insert probe row ---------------------------------------------------
say "sheet_insert_row probe=$PROBE_ID"
ins=$(mcp_call "$(jq -nc --arg c employees --arg id "$PROBE_ID" '{jsonrpc:"2.0",id:2,method:"tools/call",params:{name:"sheet_insert_row",arguments:{collection:$c,doc:{_id:$id,name:"Smoke Probe",dept:"Engineering",salary_band:"IC1"}}}}')")
echo "$ins" | jq -e '.result.isError == false' >/dev/null || fail "insert: $ins"

# ----- 3. update a cell ------------------------------------------------------
say "sheet_update_cell dept=Platform"
upd=$(mcp_call "$(jq -nc --arg c employees --arg id "$PROBE_ID" '{jsonrpc:"2.0",id:3,method:"tools/call",params:{name:"sheet_update_cell",arguments:{collection:$c,_id:$id,field:"dept",value:"Platform"}}}')")
echo "$upd" | jq -e '.result.isError == false' >/dev/null || fail "update: $upd"

# ----- 4. NL edit ------------------------------------------------------------
say "sheet_apply_nl — set salary_band to IC2 for $PROBE_ID"
nl=$(mcp_call "$(jq -nc --arg c employees --arg ins "set salary_band to IC2 for the employee with _id $PROBE_ID" '{jsonrpc:"2.0",id:4,method:"tools/call",params:{name:"sheet_apply_nl",arguments:{collection:$c,instruction:$ins}}}')")
echo "$nl" | jq -e '.result.isError == false' >/dev/null || { echo "$nl"; fail "sheet_apply_nl returned isError"; }
applied=$(echo "$nl" | jq -r '.result.content[1].text' | jq '.applied | length')
[[ "$applied" -ge 1 ]] || fail "sheet_apply_nl applied=0; result: $nl"

# ----- 5. delete probe -------------------------------------------------------
say "sheet_delete_row $PROBE_ID"
del=$(mcp_call "$(jq -nc --arg c employees --arg id "$PROBE_ID" '{jsonrpc:"2.0",id:5,method:"tools/call",params:{name:"sheet_delete_row",arguments:{collection:$c,_id:$id}}}')")
echo "$del" | jq -e '.result.isError == false' >/dev/null || fail "delete: $del"

# ----- 6. audit log grew -----------------------------------------------------
after_audit=$(audit_count)
echo "audit_log after: $after_audit"
delta=$(( after_audit - before_audit ))
[[ "$delta" -ge 4 ]] || fail "expected audit_log to grow by >=4 (insert+update+nl+delete); got $delta"

# ----- 7. web routes (best-effort, optional) ---------------------------------
if curl -sf -o /dev/null --max-time 5 "$WEB_URL/healthz"; then
  say "web /api/sheet/collections"
  curl -sS "$WEB_URL/api/sheet/collections" | jq -e '.collections | length >= 3' >/dev/null \
    || fail "web /api/sheet/collections"
fi

echo
echo "PASS — audit_log grew by $delta rows"
