# Auth & RBAC Policy (Stage 19)

> **Status: placeholder policy for POC.** This document is the system-of-record for the
> Stage-19 web auth/RBAC layer. Group names, capabilities, and seeded users here are
> **placeholders** shaped for a future internal LDAP/SSO scheme — they are config values,
> not hardcoded policy literals, so they can be swapped for real LDAP groups later without
> touching route guards.
>
> See `IMPLEMENT.md` Stage 19 for the full narrative; this doc is the condensed,
> reference-able policy. Importable into the Stage-14 Docs Wiki (`scripts/import_docs.py`).

## Assumptions

- **Production uses SSO.** `AUTH_MODE=sso` trusts a production SSO / reverse-proxy
  integration to authenticate the user and forward identity + group claims via configured
  trusted headers. **The app still performs authorization locally** from the
  group→role→capability mapping below — SSO supplies identity, not policy.
- **POC uses Basic Auth.** `AUTH_MODE=basic` provides a small Basic Auth surface backed by
  seeded fake users (see "Seeded users"). Optional `trusted_network` mode treats network
  access alone as proof of membership in the base `sg_all_users` group.
- **Identities are email-style:** `firstname.lastname@lanGarland.com`.
- **Defense-in-depth:** the web service enforces route/API permissions even if the React UI
  hides nav items. MCP write tools keep their existing gates
  (`WORKFLOW_WRITES_ENABLED`, `JIRA_WRITES_ENABLED`, `DOCS_SYNC_ENABLED`, …).
- **Least privilege:** roles unlock explicit capabilities, not broad route checks only.
- **Auditability:** privileged actions carry `actor`, `roles`, and `groups` into audit logs
  where practical.

## Group → role mapping

Group names are env-configurable (`AUTH_ALL_USERS_GROUP`, `AUTH_ADMIN_GROUP`,
`AUTH_APP_USER_GROUP`, `AUTH_AUDIT_USER_GROUP`).

| LDAP group (placeholder) | App role | Intended users | Access shape |
| --- | --- | --- | --- |
| `sg_all_users` | `viewer` | Anyone reaching the app network | Read-only landing pages, architecture/docs read, health/status. POC may assume this from network access. |
| `sg_sec_admin` | `admin` | Security/admin operators (primary audience) | Full admin: workflow orchestration, connector mgmt, Jira apply gates, docs sync, auth diagnostics, all artifacts. |
| `sg_app_user` | `app_user` | Application/database owners onboarding their systems | Onboarding flows, architecture inventory for owned apps/dbs, docs/runbook authoring, limited artifact viewing. |
| `sg_audit_users` | `audit_user` | Audit team | Pull artifacts, run reports, update Archer findings, read context from Jira/Confluence/GitHub/SNOW/Snowflake/Mongo; no infra/admin changes by default. |

A user may belong to multiple groups; effective capabilities are the **union** of all their
roles' capabilities (admin wins on conflict).

## Capability matrix

Capabilities are explicit grants (`canRunWorkflow`, `canApplyJira`, `canUpdateArcher`,
`canManageDocs`, `canEditArchitectureInventory`, `canAdminAuth`, …), checked per route.

| Capability | `viewer` | `app_user` | `audit_user` | `admin` |
| --- | --- | --- | --- | --- |
| View overview/architecture/docs | yes | yes | yes | yes |
| Chat / read-only Ask Data | optional read-only | owned app data | yes | yes |
| Edit sheet/data records | no | owned onboarding records only | only artifact metadata | yes |
| Wrangler / analytics | no/read-only | owned datasets | yes | yes |
| Workflow orchestration (`canRunWorkflow`) | no | request/preview only | report/audit workflows | yes |
| Jira staged apply (`canApplyJira`) | no | no | validate/comment only | yes |
| Archer finding update (`canUpdateArcher`) | no | no | yes | yes |
| Docs author/edit (`canManageDocs`) | read-only | own app docs/runbooks | audit artifacts/docs | yes |
| Docs Confluence sync | no | no | request only | yes |
| Architecture inventory edit (`canEditArchitectureInventory`) | no | own app/db entries | audit annotations | yes |
| Auth/admin diagnostics (`canAdminAuth`) | no | no | no | yes |

## Web API capability requirements

Each `/api/*` route declares an explicit required capability. Read endpoints stay open to
`sg_all_users`; mutations require the matching grant. Authoritative list lands with
**S19.backend.3**; the initial mapping:

| Endpoint (web `/api/*`) | Required capability |
| --- | --- |
| `GET /api/me`, `GET /api/overview`, `GET /api/topology`/`architecture`, `GET /api/docs/*` (read), health/status | authenticated (`viewer`) |
| `POST /api/ask_data`, chat reads | `viewer` (read-only) / `app_user` for owned data |
| `POST /api/docs` (upsert), `POST /api/docs/{slug}/flags` | `canManageDocs` |
| `POST /api/docs/sync`, `POST /api/docs/agent` (apply) | `admin` (sync); audit may request |
| Sheet writes, wrangler save | `app_user` (owned) / `admin` |
| Workflow run | `canRunWorkflow` |
| Jira stage/validate | `audit_user` (validate) / `admin` |
| Jira apply | `canApplyJira` (`admin`) |
| Archer finding update | `canUpdateArcher` |
| Architecture inventory edit | `canEditArchitectureInventory` |
| Auth diagnostics (`/api/auth/*`, `/admin/auth`) | `canAdminAuth` |

Guards reject with **401** if unauthenticated, **403** if authenticated but missing the
capability — even when called directly via curl (UI gating is not a security boundary).

## Auth modes

`AUTH_MODE` = `sso` | `basic` | `trusted_network` | `headers` | `ldap` | `disabled`.

- **`sso`** — production. Derive user from trusted proxy/SSO headers
  (`AUTH_TRUSTED_HEADER_USER`, `AUTH_TRUSTED_HEADER_GROUPS`). **Never** accept spoofable dev
  headers in this mode.
- **`basic`** — POC. HTTP Basic Auth against seeded users; password hashes / dev-only
  passwords stored outside committed secrets (`AUTH_BASIC_USERS_FILE`,
  `AUTH_BASIC_SEED_PASSWORD`).
- **`trusted_network`** — POC fallback. Derive user from `X-Forwarded-User`/`REMOTE_USER`
  if present, else `anonymous-network-user`; groups default to `AUTH_ALL_USERS_GROUP`.
- **`headers`** — dev/test only. `X-SG-User` / `X-SG-Groups` simulate identity+groups.
  Disabled unless `AUTH_DEV_HEADERS_ENABLED=true`; must be off in production.
- **`ldap`** — future adapter; isolated lookup interface (`lookup_user`, `lookup_groups`,
  `check_membership`). Placeholder group names are config, not hardcoded.
- **`disabled`** — local-only escape hatch.

## Seeded users (POC)

Deterministic fake users covering every group/role; passwords are POC-only (generated
hashes or gitignored dev secret), **never committed**.

| User | Login | Groups | Role coverage |
| --- | --- | --- | --- |
| Avery Stone | `avery.stone@lanGarland.com` | `sg_all_users` | base viewer |
| Simone Patel | `simone.patel@lanGarland.com` | `sg_all_users`, `sg_sec_admin` | admin |
| Marcus Chen | `marcus.chen@lanGarland.com` | `sg_all_users`, `sg_app_user` | app/db owner |
| Elena Brooks | `elena.brooks@lanGarland.com` | `sg_all_users`, `sg_audit_users` | audit user |
| Priya Morgan | `priya.morgan@lanGarland.com` | `sg_all_users`, `sg_app_user`, `sg_audit_users` | multi-role non-admin |
| Jordan Reyes | `jordan.reyes@lanGarland.com` | `sg_all_users`, `sg_sec_admin`, `sg_audit_users` | admin + audit |

## Privacy boundary (LDAP / auth agent)

Never expose full directory dumps to the model. Lookups return minimal attributes only:
username, display name, email (if needed), group names/DNs, lookup timestamp, source, and
errors. Only the web service / a locked-down auth-specialist surface may call auth lookup
tools; ordinary chat agents must not get broad identity access.

## Open questions (do not block POC basic/trusted-network mode)

- Exact real LDAP group DNs and the lookup API/adapter shape (`AUTH_LDAP_URL`,
  `AUTH_LDAP_BASE_DN`, bind secret handling) — deferred to S19.ldap.1.
- "Owned app data / records" scoping model for `app_user` — how ownership is recorded and
  enforced on sheet/wrangler/architecture rows.
- Whether SSO forwards signed group claims vs. plain headers, and the trust/verification
  for that.
- Final decision on auth explanation surface: MCP integration vs. locked-down
  auth-specialist agent vs. project skill — deferred to S19.agent.1.
- Caching strategy/TTL correctness (`AUTH_CACHE_TTL_SECONDS`) for group lookups.
