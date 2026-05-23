#!/usr/bin/env bash
# Smoke test: Stage 23 Confluence live-gate + overlap-chain seed data.
set -euo pipefail

MCP_URL="${MCP_URL:-http://localhost:5451/mcp}"

say()  { printf "\n===> %s\n" "$*"; }
fail() { printf "FAIL: %s\n" "$*"; exit 1; }

SID=$(curl -sS -i -X POST "$MCP_URL" \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{}}' \
  | grep -i mcp-session-id | awk '{print $2}' | tr -d '\r')
[[ -n "$SID" ]] || fail "no Mcp-Session-Id returned"
echo "Session: $SID"

mcp_call() {
  curl -sS --max-time 90 -X POST "$MCP_URL" \
    -H 'Content-Type: application/json' \
    -H "mcp-session-id: $SID" \
    -d "$1"
}
json_block() { echo "$1" | jq -r '.result.content[-1].text'; }

say "connector_summary confluence"
resp=$(mcp_call '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"connector_summary","arguments":{"name":"confluence"}}}')
echo "$resp" | jq -e '.result.isError == false' >/dev/null || fail "connector_summary error: $resp"
payload=$(json_block "$resp")
echo "$payload" | jq -e '.schema == "confluence_links" and (.sample_data | length) >= 6' >/dev/null \
  || fail "Confluence summary did not expose enriched canonical pages: $payload"
echo "$payload" | jq -e '[.sample_data[].matched_on.ticket_refs[]?] | index("RDS-LOG-3") != null' >/dev/null \
  || fail "Confluence summary missing RDS overlap ticket_refs"
echo "Confluence status: $(echo "$payload" | jq -r '.status'); pages=$(echo "$payload" | jq '.sample_data | length')"

say "mongo_query confluence_pages"
resp=$(mcp_call '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"mongo_query","arguments":{"collection":"confluence_pages","filter":{"matched_on.epic_keys":"RDS-LOG-1"},"limit":10}}}')
echo "$resp" | jq -e '.result.isError == false' >/dev/null || fail "mongo_query confluence_pages error: $resp"
payload=$(json_block "$resp")
echo "$payload" | jq -e '.rows and (.rows | length) >= 2' >/dev/null \
  || fail "Expected at least two RDS Confluence pages from confluence_pages: $payload"
echo "$payload" | jq -r '.rows[] | "  - \(.id) \(.title)"'

say "docs_search teaching docs"
resp=$(mcp_call '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"docs_search","arguments":{"query":"stage-23","limit":10}}}')
echo "$resp" | jq -e '.result.isError == false' >/dev/null || fail "docs_search error: $resp"
payload=$(json_block "$resp")
echo "$payload" | jq -e '[.results[].slug] | index("overlap-chain") != null and index("agentic-workflows") != null and index("mcp-in-this-stack") != null' >/dev/null \
  || fail "Teaching docs not present in wiki docs collection. Run scripts/reseed.sh or scripts/import_docs.py. Payload: $payload"

say "docs_sync remains dry-run unless all live gates are enabled"
resp=$(mcp_call '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"docs_sync","arguments":{"slug":"mcp-in-this-stack"}}}')
echo "$resp" | jq -e '.result.isError == false' >/dev/null || fail "docs_sync error: $resp"
payload=$(json_block "$resp")
echo "$payload" | jq -e '.live == false' >/dev/null || fail "docs_sync unexpectedly live without all gates: $payload"
echo "dry-run actions=$(echo "$payload" | jq '.actions | length')"

printf "\nPASS: Stage-23 Confluence/overlap smoke test green.\n"
