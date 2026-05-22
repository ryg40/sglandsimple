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

Each `/api/*` route declares an explicit required capability. Read endpoints are open to
any authenticated user (any valid identity → 401 if not authed); mutations require the
matching grant (authenticated-but-missing → 403). Wired in **S19.backend.3**.

Guards are attached via `dependencies=[Depends(_guard_cap(...))]` or
`dependencies=[Depends(_guard_user)]` in the route decorator — handler bodies are not
modified, so the S15 `ask_data` internals and all other handler logic are untouched.

`/api/me` and `/healthz` are deliberately **unguarded** (always 200).

| Endpoint | Guard / Capability | Notes |
| --- | --- | --- |
| `GET /healthz` | **none** (public) | Liveness probe |
| `GET /api/me` | **none** (public) | Always 200; unauthenticated → `authenticated: false` |
| `GET /api/overview` | authenticated (`require_user`) | Viewer+ |
| `GET /api/topology` | authenticated (`require_user`) | Viewer+ |
| `GET /api/architecture` | authenticated (`require_user`) | Viewer+ |
| `GET /api/connectors` | authenticated (`require_user`) | Viewer+ |
| `GET /api/connectors/{name}` | authenticated (`require_user`) | Viewer+ |
| `GET /api/audit/recent` | authenticated (`require_user`) | Viewer+ |
| `GET /api/sheet/collections` | authenticated (`require_user`) | Viewer+ |
| `GET /api/sheet/rows` | authenticated (`require_user`) | Viewer+ |
| `GET /api/wrangler/sample` | authenticated (`require_user`) | Viewer+ |
| `GET /api/wrangler/pipelines` | authenticated (`require_user`) | Viewer+ |
| `GET /api/jira/issues` | authenticated (`require_user`) | Viewer+ |
| `GET /api/docs/tree` | authenticated (`require_user`) | Viewer+ |
| `GET /api/docs/search` | authenticated (`require_user`) | Viewer+ |
| `GET /api/docs/{slug}` | authenticated (`require_user`) | Viewer+ |
| `GET /api/reports/download` | authenticated (`require_user`) | Report reads treated as viewer-level reads |
| `POST /api/chat` | `canReadChat` | Viewer gets this; any authenticated user |
| `POST /api/ask_data` | `canReadChat` | Viewer gets this; decorator-only, body untouched |
| `POST /api/sheet/cell` | `canEditData` | app_user, audit_user, admin |
| `POST /api/sheet/row` | `canEditData` | app_user, audit_user, admin |
| `DELETE /api/sheet/row` | `canEditData` | app_user, audit_user, admin |
| `POST /api/sheet/nl` | `canEditData` | app_user, audit_user, admin |
| `POST /api/wrangler/run` | `canEditData` | app_user, audit_user, admin |
| `POST /api/wrangler/save` | `canEditData` | app_user, audit_user, admin |
| `POST /api/wrangler/suggest` | `canEditData` | app_user, audit_user, admin |
| `POST /api/workflow/run` | `canRunWorkflow` | app_user, audit_user, admin |
| `POST /api/jira/stage` | `canValidateJira` | audit_user, admin |
| `POST /api/jira/validate` | `canValidateJira` | audit_user, admin |
| `POST /api/jira/revert` | `canApplyJira` | admin only — reverting staged edits is privileged (same gate as apply; prevents audit users from silently discarding staged work) |
| `POST /api/jira/apply` | `canApplyJira` | admin only |
| `POST /api/docs` (upsert) | `canManageDocs` | app_user, audit_user, admin |
| `POST /api/docs/{slug}/flags` | `canManageDocs` | app_user, audit_user, admin |
| `POST /api/docs/sync` | `canSyncDocs` | admin only |
| `POST /api/docs/agent` | `canSyncDocs` | admin only (docs agent apply = sync-level action) |
| `GET /{full_path:path}` (SPA fallback) | **none** (public) | Static SPA shell |

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

To (re)generate the users file: `AUTH_BASIC_SEED_PASSWORD=<secret> python3 web/auth_seed.py`.
The output path defaults to `AUTH_BASIC_USERS_FILE=/data/auth/users.json` (bind-mounted from `./perm/auth/`).

## Privacy boundary (LDAP / auth agent)

Never expose full directory dumps to the model. Lookups return minimal attributes only:
username, display name, email (if needed), group names/DNs, lookup timestamp, source, and
errors. Only the web service / a locked-down auth-specialist surface may call auth lookup
tools; ordinary chat agents must not get broad identity access.

## Decision (S19.agent.1) — Auth explanation surface

**Decision: staged combination — ship a self-contained pure module (`web/auth_explain.py`) now; wrap as MCP tool or auth-specialist agent later if needed.**

Rationale: The POC has four seeded users covering all roles and the policy logic is
already complete in `auth.py`. The explanation logic is a pure, deterministic function
(`explain_access`) that has no side effects, no broad data access, and no new
dependencies — it only touches the narrow `DirectoryAdapter.lookup_user` interface
(already privacy-bounded) plus the in-process `groups_to_roles`/`roles_to_capabilities`
derivation. Shipping it as a plain Python module is the safest, most auditable form:

- **(a) MCP integration** would expose identity lookups to any agent that can call MCP
  tools — too broad for a privacy-sensitive LDAP path. Deferred until a real LDAP adapter
  lands and the MCP tool can be scoped to `canAdminAuth`-bearing callers only.
- **(b) Locked-down auth-specialist agent** is the correct end-state for interactive
  "why does user X lack access?" queries, but adds agent infrastructure overhead that
  isn't justified for the POC.
- **(c) Project skill** would embed admin-only identity context into general Claude Code
  sessions — violates the privacy boundary for non-admin operators.
- **(d) Staged combination (chosen):** the pure module ships now and can be wrapped as
  either an MCP tool (behind `canAdminAuth`) or an auth-specialist agent at any time
  without changing the function signature.

Privacy boundaries enforced in `web/auth_explain.py`:

- Output dict is filtered to exactly: `username`, `display_name`, `groups`, `roles`,
  `capability`, `granted`, `reason`, `granting_roles`.
- Passwords, tokens, raw LDAP attributes, `email`, `source`, `lookup_ts`, and any other
  directory data are stripped before the dict is returned.
- The function calls only `DirectoryAdapter.lookup_user` — never `lookup_groups` or
  `check_membership` directly, so the adapter's own privacy contract is the only LDAP
  surface touched.
- Ordinary chat agents do not get access to this module; it is invoked only by admin
  tooling or, in future, a `canAdminAuth`-gated route/MCP tool.

## Open questions (do not block POC basic/trusted-network mode)

- Exact real LDAP group DNs and the lookup API/adapter shape (`AUTH_LDAP_URL`,
  `AUTH_LDAP_BASE_DN`, bind secret handling) — deferred to S19.ldap.1.
- "Owned app data / records" scoping model for `app_user` — how ownership is recorded and
  enforced on sheet/wrangler/architecture rows.
- Whether SSO forwards signed group claims vs. plain headers, and the trust/verification
  for that.
- Caching strategy/TTL correctness (`AUTH_CACHE_TTL_SECONDS`) for group lookups.
