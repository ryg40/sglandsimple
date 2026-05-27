# LDAP directory enrichment

Stage 32 adds a read-only MCP-side enterprise directory connector for enrichment only. It is deliberately separate from the Stage 19 `web/auth_ldap.py` RBAC adapter, whose contract remains capped to minimal auth fields.

## Runtime

- Connector: `mcp/connectors/ldap.py`
- Fixture: `mcp/fixtures/ldap_users.json`
- Generator: `scripts/seed_ldap_users.py`
- MCP tools:
  - `ldap_lookup_user`
  - `ldap_lookup_manager_chain`
  - `identity_enrichment`
- Web proxy: `GET /api/identity/{user}/enrichment`

Fixture mode returns `python-ldap`-shaped search results as `(dn, attributes)` where attributes are byte lists. Live mode is stubbed with TODO call sites so a future `python-ldap` bind/search can replace only the adapter internals.

## Environment

```env
LDAP_ENABLED=false
CONN_LDAP_ENABLED=false
LDAP_MODE=fixture
LDAP_APP_ID=sglandsimple-directory-poc
LDAP_BIND_DN=CN=sglandsimple-directory-poc,OU=Service Accounts,DC=lanGarland,DC=com
LDAP_BASE_DN=DC=lanGarland,DC=com
LDAP_SERVER_URI=
LDAP_USERS_FILE=/app/fixtures/ldap_users.json
```

Disabled mode returns a clear `directory disabled` result instead of raising.

## Data shape

The fixture contains 200 fake users with common enterprise LDAP attributes: `cn`, `displayName`, `givenName`, `sn`, `mail`, `sAMAccountName`, `uid`, `userPrincipalName`, `title`, `department`, `division`, `manager`, `directReports`, `memberOf`, `telephoneNumber`, `physicalDeliveryOfficeName`, `l`, `employeeID`, `employeeType`, and `distinguishedName`.

Manager links form a real hierarchy through team managers/directors up to `enterprise.vp`. Groups include `app-team-*` and distribution-list groups used for team inference.

## Identity enrichment

`identity_enrichment` resolves a user, infers teams from `memberOf`, returns directory summary fields (name/title/manager/team, no secrets), and checks existing read-only connector summaries for corroborating activity/context. It also derives GitHub aliases from LDAP email/uid, lists repositories with commit/PR interactions from the read-only GitHub connector history, and maps those repos to internal applications/environments when the stack has a matching app-environment mapping; otherwise the app mapping is marked `unknown`. Stage 31 incoming tickets attach this block to each ticket when the reporter or extracted user/email resolves.
