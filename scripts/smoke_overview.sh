#!/usr/bin/env bash
# Smoke test: Stage-11 compliance command center.
#
# Asserts overview_summary returns all four payload sections (kpis, attention,
# connectors, tables) and that the attention list is non-empty against the
# seeded due-date / staleness / failing-check fixtures. Also pings the web
# /api/overview proxy for parity.
set -euo pipefail

MCP_URL="${MCP_URL:-http://localhost:5451/mcp}"
WEB_URL="${WEB_URL:-http://localhost:5452}"

say()  { printf "\n===> %s\n" "$*"; }
fail() { printf "FAIL: %s\n" "$*"; exit 1; }

SID=$(curl -sS -i -X POST "$MCP_URL" \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{}}' \
  | grep -i mcp-session-id | awk '{print $2}' | tr -d '\r')
[[ -n "$SID" ]] || fail "no Mcp-Session-Id returned"
echo "Session: $SID"

mcp_call() {
  curl -sS --max-time 60 -X POST "$MCP_URL" \
    -H 'Content-Type: application/json' \
    -H "mcp-session-id: $SID" \
    -d "$1"
}
# overview_summary returns a single JSON content block.
json_block() { echo "$1" | jq -r '.result.content[0].text'; }

# ----- 1. overview_summary via MCP -------------------------------------------
say "overview_summary (MCP)"
resp=$(mcp_call '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"overview_summary","arguments":{}}}')
echo "$resp" | jq -e '.result.isError == false' >/dev/null || fail "overview_summary error: $resp"

payload=$(json_block "$resp")
for section in kpis attention connectors tables; do
  echo "$payload" | jq -e "has(\"$section\")" >/dev/null || fail "payload missing section: $section"
done
echo "sections present: kpis attention connectors tables"

# KPI shape
echo "$payload" | jq -e '.kpis | has("open_findings") and has("attention") and has("connectors_total")' >/dev/null \
  || fail "kpis missing expected keys"
echo "KPIs: $(echo "$payload" | jq -c '.kpis')"

# Attention must be non-empty given the seeded fixtures.
n=$(echo "$payload" | jq '.attention | length')
[[ "$n" -gt 0 ]] || fail "attention list is empty — did the seeds run? (reseed.sh)"
echo "attention items: $n"
echo "$payload" | jq -r '.attention[] | "  - [\(.reason)] \(.kind): \(.title)"' | head -10

# Every attention item carries the normalized shape.
echo "$payload" | jq -e '.attention | all(has("id") and has("kind") and has("reason") and has("link"))' >/dev/null \
  || fail "attention item missing normalized fields"

# At least one of each interesting reason should appear from the fixtures.
reasons=$(echo "$payload" | jq -r '[.attention[].reason] | unique | join(",")')
echo "reasons seen: $reasons"
echo "$reasons" | grep -q overdue   || fail "expected an 'overdue' item from seeds"
echo "$reasons" | grep -q blocked_pr || fail "expected a 'blocked_pr' item from the failing-check seed"

# Tables populated.
echo "$payload" | jq -e '.tables.findings | length > 0' >/dev/null || fail "tables.findings empty"
echo "$payload" | jq -e '.tables.pr_records | length > 0' >/dev/null || fail "tables.pr_records empty"

# ----- 2. web /api/overview parity -------------------------------------------
say "GET /api/overview (web proxy)"
web=$(curl -sS --max-time 60 "$WEB_URL/api/overview")
echo "$web" | jq -e 'has("kpis") and has("attention") and has("connectors") and has("tables")' >/dev/null \
  || fail "web /api/overview missing sections: $web"
echo "web proxy returned all sections; attention=$(echo "$web" | jq '.attention | length')"

printf "\nPASS: Stage-11 overview smoke test green.\n"
