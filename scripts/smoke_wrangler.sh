#!/usr/bin/env bash
# Smoke test: Stage-7 reactive aggregation builder.
#
# Exercises wrangler_sample, wrangler_run_prefix (a 4-stage tickets
# pipeline run stage-by-stage), wrangler_save_pipeline + wrangler_list_pipelines,
# and wrangler_suggest (asserts >= 2 validated pipelines come back).
set -euo pipefail

MCP_URL="${MCP_URL:-http://localhost:5451/mcp}"

say() { printf "\n===> %s\n" "$*"; }
fail() { printf "FAIL: %s\n" "$*"; exit 1; }

SID=$(curl -sS -i -X POST "$MCP_URL" \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{}}' \
  | grep -i mcp-session-id | awk '{print $2}' | tr -d '\r')
[[ -n "$SID" ]] || fail "no Mcp-Session-Id returned"
echo "Session: $SID"

mcp_call() {
  curl -sS --max-time 120 -X POST "$MCP_URL" \
    -H 'Content-Type: application/json' \
    -H "mcp-session-id: $SID" \
    -d "$1"
}
# JSON block is the 2nd content block for multi-block tools.
json_block() { echo "$1" | jq -r '.result.content[1].text'; }

# ----- 1. sample -------------------------------------------------------------
say "wrangler_sample tickets"
resp=$(mcp_call '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"wrangler_sample","arguments":{"collection":"tickets"}}}')
echo "$resp" | jq -e '.result.isError == false' >/dev/null || fail "wrangler_sample error: $resp"
json_block "$resp" | jq -e '.field_summary | length > 0' >/dev/null || fail "no field_summary"
echo "fields: $(json_block "$resp" | jq -r '[.field_summary[].field] | join(", ")')"

# ----- 2. run_prefix, stage-by-stage on a 4-stage pipeline -------------------
# [ $match open ] -> [ $group by priority count ] -> [ $sort count desc ] -> [ $limit 5 ]
PIPELINE='[{"$match":{"status":"open"}},{"$group":{"_id":"$priority","count":{"$sum":1}}},{"$sort":{"count":-1}},{"$limit":5}]'
for upto in 0 1 2 3; do
  say "wrangler_run_prefix upto=$upto"
  body=$(jq -nc --argjson p "$PIPELINE" --argjson u "$upto" \
    '{jsonrpc:"2.0",id:2,method:"tools/call",params:{name:"wrangler_run_prefix",arguments:{collection:"tickets",pipeline:$p,upto:$u}}}')
  r=$(mcp_call "$body")
  echo "$r" | jq -e '.result.isError == false' >/dev/null || fail "run_prefix upto=$upto error: $r"
  jb=$(json_block "$r")
  echo "  delta: $(echo "$jb" | jq -r '"\(.input_count) -> \(.output_count) rows (stage \(.stage_index))"')"
  echo "$jb" | jq -e '.stage_index == '"$upto" >/dev/null || fail "stage_index mismatch upto=$upto"
done

# ----- 3. save + list --------------------------------------------------------
say "wrangler_save_pipeline"
sbody=$(jq -nc --argjson p "$PIPELINE" \
  '{jsonrpc:"2.0",id:3,method:"tools/call",params:{name:"wrangler_save_pipeline",arguments:{name:"smoke top-5 open by priority",collection:"tickets",stages:$p}}}')
s=$(mcp_call "$sbody")
echo "$s" | jq -e '.result.isError == false' >/dev/null || fail "save error: $s"
pid=$(echo "$s" | jq -r '.result.content[0].text' | jq -r '._id')
[[ -n "$pid" && "$pid" != "null" ]] || fail "no pipeline id returned"
echo "  saved $pid"

say "wrangler_list_pipelines tickets"
l=$(mcp_call '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"wrangler_list_pipelines","arguments":{"collection":"tickets"}}}')
echo "$l" | jq -e '.result.isError == false' >/dev/null || fail "list error: $l"
echo "$l" | jq -r '.result.content[0].text' | jq -e --arg pid "$pid" '.pipelines | map(._id) | index($pid) != null' >/dev/null \
  || fail "saved pipeline $pid not in list"
echo "  list contains $pid"

# ----- 4. suggest ------------------------------------------------------------
say "wrangler_suggest tickets"
sg=$(mcp_call '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"wrangler_suggest","arguments":{"collection":"tickets"}}}')
n=$(echo "$sg" | jq -r '.result.content[1].text' | jq '.pipelines | length')
echo "  suggestions returned: $n"
[[ "$n" -ge 2 ]] || fail "expected >=2 validated suggested pipelines, got $n"

echo
echo "PASS — wrangler sample/run/save/list/suggest all green"
