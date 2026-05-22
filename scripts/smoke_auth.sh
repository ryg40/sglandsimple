#!/usr/bin/env bash
# Stage 19 — Auth / RBAC smoke tests.
#
# Covers:
#   1. Basic Auth login for every seeded role (six users)
#   2. Trusted-network viewer fallback (no creds → authenticated viewer)
#   3. Production-like SSO header resolution + dev-header ignored in sso mode
#   4. Dev-header simulation (headers mode, AUTH_DEV_HEADERS_ENABLED=true)
#   5. Denied admin endpoint (POST /api/workflow/run) as viewer → 403
#   6. /api/me payload shape (required keys present)
#
# MODE AWARENESS — auth mode is a server-startup env var, not a per-request
# one.  A single running instance can only test the mode it was started in.
# The script reads $AUTH_MODE (default: basic) and runs the subset of checks
# valid for that mode, printing SKIP with a clear message for others.
#
# To exercise all modes restart the web service with the desired AUTH_MODE:
#
#   AUTH_MODE=basic          AUTH_BASIC_SEED_PASSWORD=<pw>  docker compose up -d web
#   AUTH_MODE=trusted_network                               docker compose up -d web
#   AUTH_MODE=sso                                           docker compose up -d web
#   AUTH_MODE=headers        AUTH_DEV_HEADERS_ENABLED=true  docker compose up -d web
#
# Usage:
#   WEB_URL=http://localhost:5452  AUTH_MODE=basic \
#     AUTH_BASIC_SEED_PASSWORD=changeme-poc  scripts/smoke_auth.sh
#
# Prereqs:
#   - Web service running (docker compose up -d web)
#   - In basic mode: users file generated:
#       AUTH_BASIC_SEED_PASSWORD=<pw> docker exec sglandsimple-web \
#         python3 /app/auth_seed.py
#   - jq installed on the host running this script

set -euo pipefail

WEB_URL="${WEB_URL:-http://localhost:5452}"
AUTH_MODE="${AUTH_MODE:-basic}"
SEED_PASSWORD="${AUTH_BASIC_SEED_PASSWORD:-changeme-poc}"

# Group name env vars (must match what the server was started with)
ALL_USERS_GROUP="${AUTH_ALL_USERS_GROUP:-sg_all_users}"
ADMIN_GROUP="${AUTH_ADMIN_GROUP:-sg_sec_admin}"
APP_USER_GROUP="${AUTH_APP_USER_GROUP:-sg_app_user}"
AUDIT_USER_GROUP="${AUTH_AUDIT_USER_GROUP:-sg_audit_users}"

# SSO / trusted header names (must match server config)
TRUSTED_HEADER_USER="${AUTH_TRUSTED_HEADER_USER:-X-Forwarded-User}"
TRUSTED_HEADER_GROUPS="${AUTH_TRUSTED_HEADER_GROUPS:-X-Forwarded-Groups}"

PASS=0
FAIL=0
SKIP=0

say()  { printf "\n===> %s\n" "$*"; }
pass() { printf "PASS: %s\n" "$*"; PASS=$((PASS + 1)); }
fail() { printf "FAIL: %s\n" "$*"; FAIL=$((FAIL + 1)); }
skip() { printf "SKIP: %s\n" "$*"; SKIP=$((SKIP + 1)); }

# ---------------------------------------------------------------------------
# Prereq: server reachable
# ---------------------------------------------------------------------------

say "Checking server reachability: $WEB_URL/healthz"
if ! curl -sf -o /dev/null --max-time 5 "$WEB_URL/healthz"; then
  printf '\nERROR: web service not reachable at %s\n' "$WEB_URL"
  printf 'Start the stack with:\n'
  printf '  docker compose up -d web\n'
  printf 'Generate the Basic Auth users file with:\n'
  printf '  AUTH_BASIC_SEED_PASSWORD=<pw> docker exec sglandsimple-web python3 /app/auth_seed.py\n'
  printf 'Then re-run this script.\n'
  exit 1
fi
printf 'ok — server responding\n'
printf 'AUTH_MODE (local): %s\n' "$AUTH_MODE"

# ---------------------------------------------------------------------------
# Helper: GET /api/me and return the body
# ---------------------------------------------------------------------------

me_basic() {   # me_basic <email> <password>
  curl -sS --max-time 10 -u "$1:$2" "$WEB_URL/api/me"
}

me_headers() {   # me_headers [extra curl args...]
  curl -sS --max-time 10 "$@" "$WEB_URL/api/me"
}

# ---------------------------------------------------------------------------
# Helper: assert a JSON field equals an expected value
# ---------------------------------------------------------------------------

assert_eq() {   # assert_eq <label> <json> <jq_expr> <expected>
  local label="$1" json="$2" expr="$3" expected="$4"
  local actual
  actual=$(printf '%s' "$json" | jq -r "$expr" 2>/dev/null || true)
  if [[ "$actual" == "$expected" ]]; then
    pass "$label → $actual"
  else
    fail "$label: expected '$expected', got '$actual'"
  fi
}

# Helper: assert JSON array (from jq) contains a value
assert_contains() {   # assert_contains <label> <json> <jq_arr_expr> <value>
  local label="$1" json="$2" expr="$3" value="$4"
  local found
  found=$(printf '%s' "$json" | jq -r "$expr | map(. == \"$value\") | any" 2>/dev/null || true)
  if [[ "$found" == "true" ]]; then
    pass "$label contains '$value'"
  else
    fail "$label: '$value' not found in $(printf '%s' "$json" | jq -r "$expr" 2>/dev/null || true)"
  fi
}

# Helper: assert JSON array does NOT contain a value
assert_not_contains() {   # assert_not_contains <label> <json> <jq_arr_expr> <value>
  local label="$1" json="$2" expr="$3" value="$4"
  local found
  found=$(printf '%s' "$json" | jq -r "$expr | map(. == \"$value\") | any" 2>/dev/null || true)
  if [[ "$found" == "false" ]]; then
    pass "$label does not contain '$value'"
  else
    fail "$label: '$value' unexpectedly found"
  fi
}

# ---------------------------------------------------------------------------
# Check 6: /api/me payload shape
# Call this after every successful authentication assertion so we always
# validate the response envelope regardless of mode.
# ---------------------------------------------------------------------------

check_me_shape() {   # check_me_shape <label> <json>
  local label="$1" json="$2"
  local authed
  authed=$(printf '%s' "$json" | jq -r '.authenticated' 2>/dev/null || true)
  # All responses must have: authenticated, auth_mode, capabilities
  for key in authenticated auth_mode capabilities; do
    if printf '%s' "$json" | jq -e "has(\"$key\")" >/dev/null 2>&1; then
      pass "$label /api/me has key '$key'"
    else
      fail "$label /api/me missing key '$key'"
    fi
  done
  # When authenticated, additionally require: user, groups, roles
  if [[ "$authed" == "true" ]]; then
    for key in user groups roles; do
      if printf '%s' "$json" | jq -e "has(\"$key\")" >/dev/null 2>&1; then
        pass "$label /api/me authenticated has key '$key'"
      else
        fail "$label /api/me authenticated missing key '$key'"
      fi
    done
  fi
}

# ===========================================================================
# Check 1 — Basic Auth for every seeded role
# ===========================================================================

if [[ "$AUTH_MODE" == "basic" ]]; then
  say "CHECK 1: Basic Auth login for every seeded role (AUTH_MODE=basic)"

  # Six seeded users from auth_seed.py / docs/auth-rbac.md
  # Format: email | expected_role | has_canAdminAuth | has_canRunWorkflow
  declare -a USERS=(
    "avery.stone@lanGarland.com|viewer|false|false"
    "simone.patel@lanGarland.com|admin|true|true"
    "marcus.chen@lanGarland.com|app_user|false|true"
    "elena.brooks@lanGarland.com|audit_user|false|true"
    "priya.morgan@lanGarland.com|app_user|false|true"
    "jordan.reyes@lanGarland.com|admin|true|true"
  )

  for entry in "${USERS[@]}"; do
    IFS='|' read -r email role has_admin has_workflow <<< "$entry"
    say "  basic auth: $email ($role)"
    resp=$(me_basic "$email" "$SEED_PASSWORD")
    printf '  raw: %s\n' "$(printf '%s' "$resp" | jq -c '.' 2>/dev/null || printf '%s' "$resp")"

    assert_eq "  $email authenticated" "$resp" '.authenticated' "true"
    assert_eq "  $email auth_mode"     "$resp" '.auth_mode'     "basic"
    assert_eq "  $email email"         "$resp" '.user.email'    "$email"

    # all seeded users are in sg_all_users → viewer role
    assert_contains "  $email roles" "$resp" '.roles' "viewer"

    # capability checks
    if [[ "$has_admin" == "true" ]]; then
      assert_contains     "  $email caps" "$resp" '.capabilities' "canAdminAuth"
    else
      assert_not_contains "  $email caps" "$resp" '.capabilities' "canAdminAuth"
    fi
    if [[ "$has_workflow" == "true" ]]; then
      assert_contains     "  $email caps" "$resp" '.capabilities' "canRunWorkflow"
    else
      assert_not_contains "  $email caps" "$resp" '.capabilities' "canRunWorkflow"
    fi

    check_me_shape "  $email" "$resp"
  done

  # Bad password → unauthenticated (HTTP 200 but authenticated: false)
  say "  basic auth: wrong password → unauthenticated"
  resp_bad=$(me_basic "avery.stone@lanGarland.com" "wrong-password-xyz")
  assert_eq "  bad-password authenticated" "$resp_bad" '.authenticated' "false"
  check_me_shape "  bad-password" "$resp_bad"

else
  skip "CHECK 1 (basic login for seeded roles) — requires AUTH_MODE=basic, current: $AUTH_MODE"
fi

# ===========================================================================
# Check 2 — Trusted-network viewer fallback (no creds)
# ===========================================================================

if [[ "$AUTH_MODE" == "trusted_network" ]]; then
  say "CHECK 2: Trusted-network viewer fallback (AUTH_MODE=trusted_network)"

  resp=$(me_headers)
  printf '  raw: %s\n' "$(printf '%s' "$resp" | jq -c '.' 2>/dev/null || printf '%s' "$resp")"

  assert_eq "trusted_network authenticated"   "$resp" '.authenticated' "true"
  assert_eq "trusted_network auth_mode"       "$resp" '.auth_mode'     "trusted_network"
  assert_contains "trusted_network groups" "$resp" '.groups' "$ALL_USERS_GROUP"
  assert_contains "trusted_network roles"  "$resp" '.roles'  "viewer"
  check_me_shape "trusted_network" "$resp"

else
  skip "CHECK 2 (trusted-network fallback) — requires AUTH_MODE=trusted_network, current: $AUTH_MODE"
fi

# ===========================================================================
# Check 3 — SSO header resolution + dev headers ignored
# ===========================================================================

if [[ "$AUTH_MODE" == "sso" ]]; then
  say "CHECK 3a: SSO — trusted proxy header resolves identity"

  resp=$(me_headers \
    -H "${TRUSTED_HEADER_USER}: simone.patel@lanGarland.com" \
    -H "${TRUSTED_HEADER_GROUPS}: ${ALL_USERS_GROUP},${ADMIN_GROUP}")
  printf '  raw: %s\n' "$(printf '%s' "$resp" | jq -c '.' 2>/dev/null || printf '%s' "$resp")"

  assert_eq "sso authenticated"  "$resp" '.authenticated' "true"
  assert_eq "sso auth_mode"      "$resp" '.auth_mode'     "sso"
  assert_eq "sso username"       "$resp" '.user.username' "simone.patel@lanGarland.com"
  assert_contains "sso roles"   "$resp" '.roles' "admin"
  assert_contains "sso caps"    "$resp" '.capabilities' "canAdminAuth"
  check_me_shape "sso" "$resp"

  say "CHECK 3b: SSO — no proxy header → unauthenticated (no spoofing)"
  resp_no=$(me_headers)
  assert_eq "sso-no-header authenticated" "$resp_no" '.authenticated' "false"

  say "CHECK 3c: SSO — X-SG-User dev header IGNORED (hard security boundary)"
  resp_sg=$(me_headers -H "X-SG-User: hacker@evil.com" -H "X-SG-Groups: ${ADMIN_GROUP}")
  # Without the trusted proxy header, the result must be unauthenticated even
  # though X-SG-User is present — sso mode never reads dev headers.
  assert_eq "sso ignores X-SG-User authenticated" "$resp_sg" '.authenticated' "false"

else
  skip "CHECK 3 (SSO header resolution) — requires AUTH_MODE=sso, current: $AUTH_MODE"
fi

# ===========================================================================
# Check 4 — Dev-header simulation (headers mode)
# ===========================================================================

if [[ "$AUTH_MODE" == "headers" ]]; then
  say "CHECK 4: Dev-header simulation (AUTH_MODE=headers)"

  # 4a — admin via X-SG-User / X-SG-Groups
  say "  4a — admin simulation"
  resp=$(me_headers \
    -H "X-SG-User: simone.patel@lanGarland.com" \
    -H "X-SG-Groups: ${ALL_USERS_GROUP},${ADMIN_GROUP}")
  printf '  raw: %s\n' "$(printf '%s' "$resp" | jq -c '.' 2>/dev/null || printf '%s' "$resp")"
  assert_eq "headers-admin authenticated"    "$resp" '.authenticated' "true"
  assert_eq "headers-admin auth_mode"        "$resp" '.auth_mode'     "headers"
  assert_contains "headers-admin roles"      "$resp" '.roles' "admin"
  assert_contains "headers-admin caps"       "$resp" '.capabilities' "canAdminAuth"
  check_me_shape "headers-admin" "$resp"

  # 4b — app_user simulation
  say "  4b — app_user simulation"
  resp=$(me_headers \
    -H "X-SG-User: marcus.chen@lanGarland.com" \
    -H "X-SG-Groups: ${ALL_USERS_GROUP},${APP_USER_GROUP}")
  printf '  raw: %s\n' "$(printf '%s' "$resp" | jq -c '.' 2>/dev/null || printf '%s' "$resp")"
  assert_eq "headers-app_user authenticated"    "$resp" '.authenticated' "true"
  assert_contains "headers-app_user roles"      "$resp" '.roles' "app_user"
  assert_contains "headers-app_user caps"       "$resp" '.capabilities' "canRunWorkflow"
  assert_not_contains "headers-app_user caps"   "$resp" '.capabilities' "canAdminAuth"
  check_me_shape "headers-app_user" "$resp"

  # 4c — audit_user simulation
  say "  4c — audit_user simulation"
  resp=$(me_headers \
    -H "X-SG-User: elena.brooks@lanGarland.com" \
    -H "X-SG-Groups: ${ALL_USERS_GROUP},${AUDIT_USER_GROUP}")
  printf '  raw: %s\n' "$(printf '%s' "$resp" | jq -c '.' 2>/dev/null || printf '%s' "$resp")"
  assert_eq "headers-audit_user authenticated"   "$resp" '.authenticated' "true"
  assert_contains "headers-audit_user roles"     "$resp" '.roles' "audit_user"
  assert_contains "headers-audit_user caps"      "$resp" '.capabilities' "canValidateJira"
  assert_not_contains "headers-audit_user caps"  "$resp" '.capabilities' "canAdminAuth"
  check_me_shape "headers-audit_user" "$resp"

  # 4d — multi-role (app_user + audit_user)
  say "  4d — multi-role simulation (app_user + audit_user)"
  resp=$(me_headers \
    -H "X-SG-User: priya.morgan@lanGarland.com" \
    -H "X-SG-Groups: ${ALL_USERS_GROUP},${APP_USER_GROUP},${AUDIT_USER_GROUP}")
  printf '  raw: %s\n' "$(printf '%s' "$resp" | jq -c '.' 2>/dev/null || printf '%s' "$resp")"
  assert_eq "headers-multi authenticated" "$resp" '.authenticated' "true"
  assert_contains "headers-multi roles app_user"   "$resp" '.roles' "app_user"
  assert_contains "headers-multi roles audit_user" "$resp" '.roles' "audit_user"
  assert_contains "headers-multi caps canRunWorkflow" "$resp" '.capabilities' "canRunWorkflow"
  assert_contains "headers-multi caps canValidateJira" "$resp" '.capabilities' "canValidateJira"
  check_me_shape "headers-multi" "$resp"

  # 4e — no X-SG-User header → unauthenticated
  say "  4e — no X-SG-User → unauthenticated"
  resp=$(me_headers)
  assert_eq "headers-no-user authenticated" "$resp" '.authenticated' "false"

else
  skip "CHECK 4 (dev-header simulation) — requires AUTH_MODE=headers + AUTH_DEV_HEADERS_ENABLED=true, current: $AUTH_MODE"
fi

# ===========================================================================
# Check 5 — Denied admin endpoint as non-admin + allowed as privileged user
#
# POST /api/workflow/run requires canRunWorkflow.
# Viewer (avery.stone, only canReadChat) → must get 403.
# Admin (simone.patel, has canRunWorkflow) → must NOT be 403.
# Non-403 from admin may be 4xx/5xx if MCP/upstream is down — that is fine;
# the guard has passed (the guard is enforced before the MCP call).
# ===========================================================================

if [[ "$AUTH_MODE" == "basic" ]]; then
  say "CHECK 5a: viewer → 403 on POST /api/workflow/run (requires canRunWorkflow)"
  http_code=$(curl -sS -o /dev/null -w '%{http_code}' \
    -u "avery.stone@lanGarland.com:${SEED_PASSWORD}" \
    -X POST -H 'Content-Type: application/json' \
    -d '{"finding_id":"smoke-probe"}' \
    "$WEB_URL/api/workflow/run")
  if [[ "$http_code" == "403" ]]; then
    pass "viewer → 403 (guard enforced)"
  else
    fail "viewer → expected 403, got $http_code"
  fi

  say "CHECK 5b: admin → NOT 403 on POST /api/workflow/run (guard passed)"
  http_code=$(curl -sS -o /dev/null -w '%{http_code}' \
    -u "simone.patel@lanGarland.com:${SEED_PASSWORD}" \
    -X POST -H 'Content-Type: application/json' \
    -d '{"finding_id":"smoke-probe"}' \
    "$WEB_URL/api/workflow/run")
  if [[ "$http_code" != "403" ]]; then
    pass "admin → $http_code (not 403; guard passed — MCP/upstream may be down)"
  else
    fail "admin → unexpected 403 (admin has canRunWorkflow and should not be blocked)"
  fi

elif [[ "$AUTH_MODE" == "headers" ]]; then
  say "CHECK 5a: viewer header → 403 on POST /api/workflow/run"
  http_code=$(curl -sS -o /dev/null -w '%{http_code}' \
    -H "X-SG-User: avery.stone@lanGarland.com" \
    -H "X-SG-Groups: ${ALL_USERS_GROUP}" \
    -X POST -H 'Content-Type: application/json' \
    -d '{"finding_id":"smoke-probe"}' \
    "$WEB_URL/api/workflow/run")
  if [[ "$http_code" == "403" ]]; then
    pass "viewer-header → 403 (guard enforced)"
  else
    fail "viewer-header → expected 403, got $http_code"
  fi

  say "CHECK 5b: admin header → NOT 403 on POST /api/workflow/run"
  http_code=$(curl -sS -o /dev/null -w '%{http_code}' \
    -H "X-SG-User: simone.patel@lanGarland.com" \
    -H "X-SG-Groups: ${ALL_USERS_GROUP},${ADMIN_GROUP}" \
    -X POST -H 'Content-Type: application/json' \
    -d '{"finding_id":"smoke-probe"}' \
    "$WEB_URL/api/workflow/run")
  if [[ "$http_code" != "403" ]]; then
    pass "admin-header → $http_code (not 403; guard passed)"
  else
    fail "admin-header → unexpected 403"
  fi

elif [[ "$AUTH_MODE" == "sso" ]]; then
  say "CHECK 5a: viewer SSO → 403 on POST /api/workflow/run"
  http_code=$(curl -sS -o /dev/null -w '%{http_code}' \
    -H "${TRUSTED_HEADER_USER}: avery.stone@lanGarland.com" \
    -H "${TRUSTED_HEADER_GROUPS}: ${ALL_USERS_GROUP}" \
    -X POST -H 'Content-Type: application/json' \
    -d '{"finding_id":"smoke-probe"}' \
    "$WEB_URL/api/workflow/run")
  if [[ "$http_code" == "403" ]]; then
    pass "viewer-sso → 403 (guard enforced)"
  else
    fail "viewer-sso → expected 403, got $http_code"
  fi

  say "CHECK 5b: admin SSO → NOT 403 on POST /api/workflow/run"
  http_code=$(curl -sS -o /dev/null -w '%{http_code}' \
    -H "${TRUSTED_HEADER_USER}: simone.patel@lanGarland.com" \
    -H "${TRUSTED_HEADER_GROUPS}: ${ALL_USERS_GROUP},${ADMIN_GROUP}" \
    -X POST -H 'Content-Type: application/json' \
    -d '{"finding_id":"smoke-probe"}' \
    "$WEB_URL/api/workflow/run")
  if [[ "$http_code" != "403" ]]; then
    pass "admin-sso → $http_code (not 403; guard passed)"
  else
    fail "admin-sso → unexpected 403"
  fi

elif [[ "$AUTH_MODE" == "trusted_network" ]]; then
  # trusted_network always gives viewer regardless of headers; no way to get
  # canRunWorkflow without changing the mode.
  say "CHECK 5: trusted_network — POST /api/workflow/run → 403 (viewer-only mode)"
  http_code=$(curl -sS -o /dev/null -w '%{http_code}' \
    -X POST -H 'Content-Type: application/json' \
    -d '{"finding_id":"smoke-probe"}' \
    "$WEB_URL/api/workflow/run")
  if [[ "$http_code" == "403" ]]; then
    pass "trusted_network viewer → 403 (guard enforced)"
  else
    fail "trusted_network viewer → expected 403, got $http_code"
  fi
  skip "CHECK 5b (privileged access guard) — no elevated identity available in trusted_network mode"

elif [[ "$AUTH_MODE" == "disabled" ]]; then
  skip "CHECK 5 (403 guard check) — AUTH_MODE=disabled grants all capabilities; 403 guard cannot fire"

else
  skip "CHECK 5 (403 guard check) — mode '$AUTH_MODE' not handled by this check"
fi

# ===========================================================================
# Check 6 — /api/me payload shape (always reachable, mode-agnostic)
# ===========================================================================

say "CHECK 6: /api/me payload shape (no creds, expect unauthenticated envelope)"
resp=$(me_headers)
printf '  raw: %s\n' "$(printf '%s' "$resp" | jq -c '.' 2>/dev/null || printf '%s' "$resp")"
check_me_shape "unauthenticated-me" "$resp"
# Unauthenticated envelope must have authenticated=false and no 'user' key leak
assert_eq "unauthenticated authenticated" "$resp" '.authenticated' "false"
if printf '%s' "$resp" | jq -e 'has("user")' >/dev/null 2>&1; then
  fail "unauthenticated /api/me must not expose 'user' key"
else
  pass "unauthenticated /api/me does not expose 'user' key"
fi

# ===========================================================================
# Summary
# ===========================================================================

printf '\n================================================\n'
printf 'Auth smoke results  (AUTH_MODE=%s)\n' "$AUTH_MODE"
printf '  PASS: %d\n' "$PASS"
printf '  FAIL: %d\n' "$FAIL"
printf '  SKIP: %d\n' "$SKIP"
printf '================================================\n'

if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
