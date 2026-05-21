#!/usr/bin/env bash
# Smoke test: the web service serves the built React SPA and still proxies
# /api to MCP. Run after `docker compose up -d web`.
set -euo pipefail

WEB_URL="${WEB_URL:-http://localhost:5452}"

say() { printf "\n===> %s\n" "$*"; }
fail() { printf "FAIL: %s\n" "$*"; exit 1; }

# ----- 1. index.html served at root -----------------------------------------
say "GET / (SPA index)"
index=$(curl -sS "$WEB_URL/")
echo "$index" | grep -q '<div id="root">' || fail "root did not return the SPA index.html"
asset=$(echo "$index" | grep -oE '/assets/index-[A-Za-z0-9_-]+\.js' | head -1)
[[ -n "$asset" ]] || fail "no hashed JS asset referenced in index.html"
echo "  asset: $asset"

# ----- 2. hashed asset resolves ---------------------------------------------
say "GET $asset"
code=$(curl -sS -o /dev/null -w '%{http_code}' "$WEB_URL$asset")
[[ "$code" == "200" ]] || fail "hashed asset did not 200 (got $code)"

# ----- 3. SPA fallback for a client route -----------------------------------
say "GET /sheet (SPA fallback)"
sheet=$(curl -sS "$WEB_URL/sheet")
echo "$sheet" | grep -q '<div id="root">' || fail "/sheet did not fall back to index.html"

# ----- 4. /api still returns JSON -------------------------------------------
say "GET /api/sheet/collections (proxy)"
curl -sS "$WEB_URL/api/sheet/collections" | jq -e '.collections | length >= 1' >/dev/null \
  || fail "/api/sheet/collections did not return JSON collections"

# ----- 5. /api/audit/recent (new Stage-8 feed) ------------------------------
say "GET /api/audit/recent"
curl -sS "$WEB_URL/api/audit/recent?limit=5" | jq -e 'has("rows")' >/dev/null \
  || fail "/api/audit/recent missing rows"

# ----- 6. unknown /api path 404s (not swallowed by SPA fallback) ------------
say "GET /api/does-not-exist (should 404)"
code=$(curl -sS -o /dev/null -w '%{http_code}' "$WEB_URL/api/does-not-exist")
[[ "$code" == "404" ]] || fail "unknown /api path should 404, got $code"

echo
echo "PASS — SPA served, assets resolve, fallback works, /api intact"
