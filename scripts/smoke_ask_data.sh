#!/usr/bin/env bash
# Smoke test: hit MCP with three canonical questions and assert
# schema-valid output on the second (JSON) content block.
set -euo pipefail

MCP_URL="${MCP_URL:-http://localhost:5451/mcp}"

# Initialize and grab a session id
SID=$(curl -sS -i -X POST "$MCP_URL" \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{}}' \
  | grep -i mcp-session-id | awk '{print $2}' | tr -d '\r')
echo "Session: $SID"

declare -a QUESTIONS=(
  "who manages alice?"
  "open tickets per priority"
  "documents tagged onboarding"
)

pass=0
fail=0

for q in "${QUESTIONS[@]}"; do
  echo
  echo "===> $q"
  body=$(cat <<EOF
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"ask_data","arguments":{"question":"$q"}}}
EOF
)
  resp=$(curl -sS --max-time 300 -X POST "$MCP_URL" \
    -H 'Content-Type: application/json' \
    -H "mcp-session-id: $SID" \
    -d "$body")
  echo "$resp" | jq -e '.result.isError == false' >/dev/null \
    || { echo "FAIL: isError flag set: $resp"; fail=$((fail+1)); continue; }
  # Second content block must be JSON with answer/evidence/query_used.
  json_text=$(echo "$resp" | jq -r '.result.content[1].text')
  echo "$json_text" | jq -e '.answer and .evidence and .query_used' >/dev/null \
    || { echo "FAIL: JSON shape missing required keys: $json_text"; fail=$((fail+1)); continue; }
  echo "PASS"
  pass=$((pass+1))
done

echo
echo "passed: $pass / $((pass+fail))"
[[ $fail -eq 0 ]]