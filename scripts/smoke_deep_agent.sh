#!/usr/bin/env bash
# Smoke test: drive the deep_agent end-to-end and assert that
#   (1) the planner emits a Plan with >= 2 steps,
#   (2) the builder writes the requested files into ./sandbox/,
#   (3) Mongo gets a deep_agent_plans + deep_agent_runs row,
#   (4) the run summary returns isError=false.
set -euo pipefail

MCP_URL="${MCP_URL:-http://localhost:5451/mcp}"
SANDBOX_DIR="${SANDBOX_DIR:-./sandbox}"
GOAL="${GOAL:-Create three files in the sandbox: a.txt with content A, b.txt with content B, and c.txt with content C. Then run ls -la to verify.}"

# Initialize and grab a session id.
SID=$(curl -sS -i -X POST "$MCP_URL" \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{}}}' \
  | grep -i mcp-session-id | awk '{print $2}' | tr -d '\r')
echo "Session: $SID"

# Clear stale files so we can assert on freshly-created ones.
rm -f "$SANDBOX_DIR"/a.txt "$SANDBOX_DIR"/b.txt "$SANDBOX_DIR"/c.txt 2>/dev/null || true

echo
echo "===> deep_agent: $GOAL"

MCP_URL="$MCP_URL" SID="$SID" GOAL="$GOAL" python3 - <<'PY'
import json, os, sys, urllib.request

mcp = os.environ["MCP_URL"]
sid = os.environ["SID"]
goal = os.environ["GOAL"]

req = urllib.request.Request(
    mcp,
    method="POST",
    headers={"Content-Type": "application/json", "Mcp-Session-Id": sid},
    data=json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "deep_agent", "arguments": {"goal": goal}},
        }
    ).encode("utf-8"),
)
with urllib.request.urlopen(req, timeout=300) as resp:
    data = json.loads(resp.read().decode("utf-8"))

if "error" in data:
    print("FAIL: RPC error:", data["error"])
    sys.exit(1)

result = data.get("result", {})
blocks = result.get("content", [])
if result.get("isError"):
    print("FAIL: tool returned isError")
    for b in blocks:
        print(b.get("text", ""))
    sys.exit(1)
if len(blocks) < 2:
    print(f"FAIL: expected 2 content blocks, got {len(blocks)}")
    sys.exit(1)

payload = json.loads(blocks[1]["text"])
plan = payload.get("plan", {})
summary = payload.get("summary", {})
steps = plan.get("steps", [])
results = summary.get("results", [])
oks = sum(1 for r in results if r.get("status") == "ok")
errs = sum(1 for r in results if r.get("status") == "error")
print(f"plan_id={plan.get('plan_id')}")
print(f"steps={len(steps)} (tools: {[s['tool'] for s in steps]})")
print(f"results: ok={oks} err={errs}")
if len(steps) < 2:
    print("FAIL: plan has fewer than 2 steps")
    sys.exit(1)
if errs:
    print("FAIL: at least one step errored")
    sys.exit(1)
print("PASS: deep_agent end-to-end succeeded")
PY

# Filesystem assertion.
echo
echo "--- sandbox listing ---"
ls -la "$SANDBOX_DIR"
for f in a.txt b.txt c.txt; do
    if [[ ! -f "$SANDBOX_DIR/$f" ]]; then
        echo "FAIL: $SANDBOX_DIR/$f not created"
        exit 1
    fi
done
echo "PASS: sandbox files present"

# Mongo persistence assertion.
echo
echo "--- mongo persistence ---"
docker compose exec -T mongo mongosh --quiet \
    -u "${MONGO_ROOT_USER:-root}" -p "${MONGO_ROOT_PASSWORD:-rootpw}" \
    --authenticationDatabase admin --eval '
    db = db.getSiblingDB("enterprise");
    var plans = db.deep_agent_plans.countDocuments({});
    var runs = db.deep_agent_runs.countDocuments({});
    print("plans=" + plans + " runs=" + runs);
    if (plans < 1 || runs < 1) { print("FAIL: missing plan or run rows"); quit(1); }
    print("PASS: plan + run persisted");
'

echo
echo "ALL CHECKS PASSED"
