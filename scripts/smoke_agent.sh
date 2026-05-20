#!/usr/bin/env bash
# Smoke test: confirm the OpenAI-compatible agent dispatches to ask_data
# end-to-end. The model receives a question that should make it call
# ask_data, and the final assistant message should reference at least one
# Mongo _id (we look for "emp-" or "tkt-" or "doc-").
set -euo pipefail

AGENT_URL="${AGENT_URL:-http://localhost:5450/v1/chat/completions}"

body=$(cat <<'EOF'
{
  "model": "qwen3.6-27b",
  "messages": [
    {"role": "system", "content": "You have access to enterprise data via tools. When asked about employees, tickets, or documents, call the ask_data tool with the user's question."},
    {"role": "user", "content": "Use ask_data to answer: who manages alice in the engineering department?"}
  ]
}
EOF
)

resp=$(curl -sS -X POST "$AGENT_URL" -H 'Content-Type: application/json' -d "$body")
content=$(echo "$resp" | jq -r '.choices[0].message.content // ""')
echo "--- assistant ---"
echo "$content"
echo "-----------------"
if echo "$content" | grep -Eq '(emp-[0-9]+|tkt-[0-9]+|doc-[0-9]+)'; then
  echo "PASS — found a Mongo _id reference."
else
  echo "FAIL — no Mongo _id reference in the final answer."
  exit 1
fi
