# Architecture Inventory Template

> **Purpose.** This is the data-capture form for the Stage-18 architecture diagram v2
> (`/architecture`). It lists every technical detail the diagram reserves fields for so
> platform, network, and application-owner teams can fill them in over time. The diagram
> is usable today with mock/placeholder data; this template turns the placeholders into
> real, owner-supplied facts.
>
> **Rules for filling this in:**
> - Use `TBD` for anything not yet known. **Never invent** IPs, account IDs, CIDRs, or
>   hostnames — a wrong-but-plausible value is worse than `TBD`.
> - One row/section per system or environment. Add rows freely; the headings are the
>   contract, the example values are illustrative only.
> - Mark sensitive values (real account IDs, private IPs, secrets) per your data-handling
>   policy; this doc is intended for the internal Docs Wiki, not public Confluence sync.
> - Keep `kind` / system names aligned with the connector registry
>   (`archer`, `servicenow`, `jira`, `github`, `confluence`, `aws`, `mongodb`, `snowflake`)
>   plus any non-connector infrastructure nodes you add.

---

## 1. Environments / accounts (the boundary boxes)

For each environment the estate spans. These become the group/lane boxes on the diagram.

| Field | Example | Notes |
| --- | --- | --- |
| `id` | `aws-prod` | Stable slug used by the graph |
| `label` | `AWS — Production` | Human-readable |
| `kind` | `aws_account` \| `azure_subscription` \| `gcp_project` \| `on_prem_zone` \| `saas` | Drives icon/grouping |
| `cloud` | `aws` \| `azure` \| `gcp` \| `on_prem` \| `saas` | |
| `account_id` / `subscription_id` / `project_id` | `TBD` | Real identifier per cloud; redact per policy |
| `region(s)` | `TBD` | e.g. `us-east-1`; list all in use |
| `owner` | `TBD` | Team/DL responsible |
| `data_classification` | `TBD` | e.g. `internal` / `confidential` / `restricted` |
| `criticality` | `TBD` | e.g. `tier-1` |
| `notes / known unknowns` | | Anything still pending and from whom |

### Environments to enumerate (at minimum)

- [ ] On-prem network zone(s)
- [ ] AWS account(s) — prod / non-prod
- [ ] Azure subscription(s)
- [ ] GCP project(s)
- [ ] Atlassian (Jira + Confluence) — SaaS
- [ ] GitHub org — SaaS
- [ ] ServiceNow — SaaS
- [ ] Archer / RISK — SaaS or on-prem
- [ ] Snowflake — SaaS / analytics

---

## 2. AWS network detail (per AWS account)

| Field | Example | Notes |
| --- | --- | --- |
| `account_id` | `TBD` | |
| `region` | `TBD` | |
| `vpc_id` | `TBD` | One row per VPC |
| `vpc_cidr` | `TBD` | |
| `subnet_id` | `TBD` | One row per subnet |
| `subnet_cidr` | `TBD` | |
| `subnet_tier` | `TBD` | `public` / `private` / `data` |
| `security_groups` | `TBD` | SG ids + intent |
| `route/peering/transit-gateway` | `TBD` | How this VPC reaches others / on-prem |

---

## 3. Compute & data nodes (the boxes inside environments)

One section per node (EC2 instance, managed service, SaaS endpoint, etc.).

| Field | Example | Notes |
| --- | --- | --- |
| `id` | `ec2-mongo-wh` | Stable slug |
| `label` | `MongoDB Warehouse` | |
| `kind` | `ec2_mongodb` \| `ec2` \| `rds` \| `s3` \| `lambda` \| `saas` \| … | |
| `layer_id` / `environment` | `aws-prod` | Which boundary box it sits in |
| `hostname` | `TBD` | |
| `private_ip` | `TBD` | Redact per policy |
| `public_url` | `TBD` | If publicly reachable |
| `instance_type` | `TBD` | e.g. `m6i.2xlarge` |
| `storage_gb` | `TBD` | |
| `retention_days` | `TBD` | For log/evidence stores |
| `owner` | `TBD` | |
| `data_classification` | `TBD` | |
| `criticality` | `TBD` | |
| `runbook_slug` | `TBD` | Links node → Docs Wiki runbook (Stage 14) |

### The central evidence store (call out explicitly)

- [ ] EC2-hosted **MongoDB** NoSQL fork / data warehouse — instance type, storage, retention, backup, replication topology (`TBD`).
- [ ] Optional **Snowflake** / analytical store — account, warehouse size, retention (`TBD`).
- [ ] Log pipelines feeding the warehouse from on-prem / AWS / Azure / GCP (`TBD`).

---

## 4. Integrations / edges (how systems connect)

One row per directed integration (these become the diagram's edges and the data-flow overlay).

| Field | Example | Notes |
| --- | --- | --- |
| `from` → `to` | `servicenow` → `jira` | Source/target node ids |
| `label` | `finding → ticket` | Plain-English |
| `direction` | `one-way` / `bidirectional` | |
| `protocol` / `transport` | `REST` \| `webhook` \| `log shipper` \| `MCP tool` \| `agent workflow` \| `SQL/export` | |
| `auth_mode` | `TBD` | e.g. `OAuth` / `API token` / `IAM role` |
| `endpoint_ref` | `TBD` | URL or reference; redact secrets |
| `frequency` | `TBD` | e.g. `realtime webhook` / `hourly` |
| `sla` | `TBD` | |
| `agentic_status` | `current` \| `planned` \| `experimental` | Distinguishes live wiring from planned agentic workflows |

### Canonical data flow to confirm (RISK → artifact)

Confirm/annotate each hop of the Stage-18 flow `risk_to_artifact`:

1. [ ] Findings/incidents/changes originate in **Archer/RISK** and **ServiceNow/SNOW**.
2. [ ] Findings become **Jira** epics/issues and **Confluence** epic logs (protocol? `TBD`).
3. [ ] Implementation in **GitHub** / CI-CD and agentic workflows (status? `current`/`planned`).
4. [ ] Logs/evidence/tickets/docs/PR records land in the **MongoDB** warehouse (pipelines? `TBD`).
5. [ ] **Observability/analytics** read from the warehouse / Snowflake (`TBD`).
6. [ ] **Artifact generation** emits PDFs/PPTs/audit packets, updates docs/tickets.

---

## 5. Known unknowns (surfaced in the UI)

Track outstanding details so the diagram's "Known unknowns" panel can show what is still
pending and who owns the answer. Do not fill gaps with guesses.

| Missing detail | Owner / team | Environment | Requested on | Status |
| --- | --- | --- | --- | --- |
| (e.g. prod VPC CIDR) | network team | `aws-prod` | `TBD` | open |

---

## 6. How to use this template

- This file is importable into the **Stage-14 Docs Wiki** (`scripts/import_docs.py` walks
  `docs/*.md`), so it becomes a living wiki doc rather than a static file.
- As real values arrive, they feed the Stage-18 architecture graph schema
  (`mcp/architecture.py` / `topology.py`) — the field names above match the schema's
  reserved metadata keys (`account_id`, `vpc_id`, `subnet_id`, `cidr`, `instance_type`,
  `retention_days`, `runbook_slug`, integration `protocol`/`auth_mode`/`agentic_status`, …).
- Where a node has a `runbook_slug`, the architecture page links the node to that wiki doc.
