# Deep Agent platform (Stage 21) — design

> **Status:** design doc for Stage 21 (`S21.arch.1`). The code described under
> "Target architecture" is the *plan*; only the Stage-4 baseline it builds on
> exists today. This doc is the contract the rest of the `S21.*` tasks
> implement against. For the Stage-4 primitive itself, see
> [`deep_agent.md`](deep_agent.md); this doc does not repeat it.

## 1. What this stage is

Stage 4 shipped a single planner→builder subagent pair (`plan_task` /
`run_plan` / `deep_agent`). It works, but it is **one generic agent with one
global tool catalog**: any plan can call any non-excluded MCP tool, there is
no per-task scope, no first-class human-in-the-loop (HITL) gate, no run
registry the UI can drive, and no deployment story beyond "it runs inside the
`mcp` container."

Stage 21 turns that primitive into a **platform**: a small set of
**service-specific agents**, each with a strict tool allowlist, a context
pack, a model/budget profile, and a write policy; a **supervising
orchestrator** that routes a goal to the right agent; **typed HITL approval
gates** that survive restart; a **runtime API** (`agent_run_*`) that web, MCP,
and background callers share; and a **deployment path** (compose → ECS/Fargate
or K8s, optional Bedrock provider).

The guiding principle is the one already enforced everywhere in this repo:
**all graph code stays server-side, all production writes are dry-run until an
explicit HITL approval, and least privilege is the default** — a Jira agent
never sees AWS credentials or the docs-sync tool.

## 2. Relationship to Stage 4 (what we keep, what we change)

Stage 4 lives in `mcp/deep_agent/` and gives us the primitives to reuse:

| Stage-4 piece | File | Stage-21 disposition |
| --- | --- | --- |
| `Plan` / `Step` / `StepResult` Pydantic models | `deep_agent/models.py` | **Keep.** Add `RunRecord`, `Proposal`, `ApprovalRequest`, `ApprovalDecision` typed models alongside. |
| Planner: goal → `Plan` (one structured LLM call, validated against the live catalog) | `deep_agent/planner.py` | **Keep, parameterize.** The planner now receives a *profile-scoped* catalog, not the global one. |
| Builder: execute steps, re-plan on failure, summarize | `deep_agent/builder.py` | **Keep, parameterize.** Step dispatch is gated by the profile allowlist + policy. |
| Tool catalog with a single global `_EXCLUDED` denylist | `deep_agent/catalog.py` | **Change — this is the central seam.** See §3. |
| Planner/builder role split via `structured(..., role=)` | `mcp/llm.py` | **Keep.** Add an optional provider dimension (`openai` / `bedrock`) per profile. |
| Mongo persistence of plans | `deep_agent_plans` collection | **Extend.** Add `deep_agent_runs` (run metadata/traces/artifacts) + `deep_agent_checkpoints` for resumable HITL. |
| Token budget / step / runtime caps | `deep_agent/budget.py` | **Keep, per-profile.** Budgets move into the profile. |
| Checkpointer | `checkpointer.py` (`checkpointer_context`) | **Keep.** It already backs `ask_data`/`docs_agent`; reuse for HITL interrupt/resume. |

**The one structural change that everything else hangs off:** today
`deep_agent/catalog.py` exposes *one* catalog to *every* plan, filtered only by
a hardcoded `_EXCLUDED = {"plan_task", "run_plan", "deep_agent", "chat",
"summarize_text", "echo"}` recursion guard. Stage 21 replaces "one global
denylist" with "**one allowlist per profile**": the catalog functions
(`tool_names`, `catalog_markdown`, `focused_catalog_markdown`) take a profile
(or its allowed-tool set) and return only those tools. The recursion guard
stays as a floor that no profile can override. This is what makes a
"Jira agent" actually a Jira agent and not a fully-capable agent that happens
to be asked a Jira question.

## 3. Profile model

A **profile** is the unit of scope. It is declarative config (`profiles.yaml`,
loaded by `deep_agent/profiles.py`, validated at startup — invalid profiles
fail fast). Shape:

```yaml
- name: jira_agent
  description: Jira issue triage and staged edits.
  model_role: builder            # planner | builder; maps to PLANNER_*/BUILDER_*
  provider: openai               # openai | bedrock
  allowed_tools:                 # the per-profile allowlist (replaces global _EXCLUDED)
    - jira_stage_edits
    - jira_validate_staged
    - jira_revert_staged
    - docs_search
  context_packs: [jira_story_template, standup_labels]
  write_policy: dry_run_only     # read_only | dry_run_only | write_capable
  required_capability: canApplyJira   # Stage-19 capability gate (may be null)
  budget_tokens: 70000
  max_steps: 25
  max_seconds: 900
```

Baseline profiles (§21b of the plan), each with a non-overlapping allowlist:

| Profile | Write policy | Allowed-tool theme | Stage-19 capability |
| --- | --- | --- | --- |
| `jira_agent` | `dry_run_only` | Jira staging tools, Jira templates, docs search | `canApplyJira` |
| `docs_agent` | `dry_run_only` | `docs_*`, `docs_sync` (gated) | `canManageDocs` |
| `architecture_agent` | `read_only` | architecture graph, docs/runbooks, connector summaries | — |
| `audit_agent` | `dry_run_only` | report tools, Archer/SNOW/Snowflake/Mongo *reads*, docs search | `canUpdateArcher` |
| `workflow_agent` | `dry_run_only` | Stage-9 workflow tools + connector registry | `canRunWorkflow` |
| `auth_agent` | `read_only` | auth lookup/explain tools only | `canAdminAuth` |
| `standup_agent` | `dry_run_only` | standup session data, Jira/docs templates | `canApproveStandupActions` |

`write_policy` and `required_capability` are enforced **twice**: at planner
catalog-construction time (the agent literally cannot see a tool outside its
allowlist) and again at builder dispatch time (a fabricated step name fails
closed and is recorded as a policy event). Defense in depth — the same posture
as the web layer enforcing route permissions even when the UI hides nav items.

## 4. Context packs

Profiles reference **context packs** (`deep_agent/context.py`): compact,
versioned bundles of the templates / schemas / examples / runbook links an
agent needs, requested by name. This keeps prompts small (the whole reason
Stage 4 split planner/builder) and avoids dumping the entire Docs Wiki into
context. Packs are sourced from existing material — the Stage-9 Jira story
template, `mcp/standup_agent.py`'s deterministic story-template context,
Stage-14 `docs_*` queries, the Stage-18 architecture inventory template — not
invented fresh. A pack is `{name, version, blocks[]}`; an agent loads only its
declared packs.

## 5. HITL interrupt/resume contract

Reuse the pattern already proven by the Stage-14 docs agent: a checkpointed
`StateGraph` that **interrupts** at an apply gate and **resumes** by
`thread_id` with a typed decision. Generalized here:

- A write-capable run reaches an `apply_gate` node and **interrupts**,
  persisting a typed `ApprovalRequest` (what will be written, to which
  service, the dry-run payload, the validation result, rationale, source refs).
- The run's `run_id` + `status="waiting_approval"` is returned to the caller;
  nothing is written.
- An approver calls `agent_run_resume` with `{run_id, decision}` where decision
  is approve / reject / edited-payload. The capability of the resuming actor is
  checked server-side against the profile's `required_capability`.
- On approve, the run resumes from the checkpoint and applies *only* approved
  proposals through the existing staged-write paths (e.g. Stage-16
  `jira_validate_staged` / `jira_apply_staged`), still subject to
  `JIRA_WRITES_ENABLED` and `DEEP_AGENT_DRY_RUN_ONLY`.
- Because state is checkpointed to Mongo, a pending approval **survives a
  container restart** (verified in `S21.verify.2`).

`DEEP_AGENT_DRY_RUN_ONLY=true` is a global guardrail that suppresses live
apply for *every* profile regardless of connector write gates — the POC-safe
default.

## 6. Runtime API

Added as MCP tools **and** `web/main.py` `/api/agents/*` proxies, so the web UI,
IDE/MCP clients, and background jobs share one runtime (typed request/response
models, no `any` on the TS side):

| Tool | Purpose |
| --- | --- |
| `agent_profiles_list` | Profiles, scopes, required capabilities, allowed tools. |
| `agent_run_start` | Start a typed run `{agent, goal, context_refs, mode}`. |
| `agent_run_status` | Graph state, current node, tool calls, budget, pending approvals. |
| `agent_run_resume` | Resume from HITL interrupt (approve/reject/edited payload). |
| `agent_run_cancel` | Cancel and persist a terminal state. |
| `agent_run_artifacts` | Fetch proposals/reports/docs/patches/logs for a run. |

An orchestrator entry point (`agent_run_start` with no explicit `agent`, or a
dedicated supervisor) routes a goal to a profile by intent + UI context, then
delegates — it does not itself hold a broad tool catalog.

## 7. Security, audit, observability

- Every run carries `actor`, `source` (`web`/`mcp`/`standup`/`workflow`),
  profile, role/capability snapshot, and a correlation id.
- Tool inputs/outputs are persisted with **secret redaction**; denied tool
  calls are persisted as policy events (not silently dropped).
- Approvals record actor, groups/roles, timestamp, original proposal, edited
  proposal, validation result, and apply result.
- Structured logs for node start/end, tool-call start/end, budget, approvals,
  failures, retries, cancellations. A `/metrics` (or tool-exposed) surface
  counts active/completed/failed runs, pending approvals, token usage,
  tool-call counts, and per-profile latency.
- An admin UI route (`/agents`, admin-only) lists profiles, starts runs,
  inspects status/tool-calls/artifacts, shows pending approvals, and
  resumes/cancels.

## 8. Deployment architecture

`DEEP_AGENT_RUNTIME_MODE` selects where the runtime lives:

- **`in_mcp` (default / baseline):** runtime is code inside the existing `mcp`
  container — no new service. This is the compose baseline and what the POC
  ships.
- **`sidecar`:** an `agent-runtime` container in the same compose stack /
  task, isolated from the MCP request path, sharing Mongo + checkpointer.
- **`remote`:** runtime addressed over the network (ECS/Fargate service or K8s
  deployment).

Managed targets (blueprint-level for at least one in this stage):

- **ECS/Fargate:** task role, secrets from Secrets Manager/SSM, CloudWatch
  logs, VPC reachability to Mongo/warehouse and connector endpoints.
- **Kubernetes:** Helm/Kustomize manifests, config maps for profiles, secrets
  for model/connector creds, HPA on concurrent runs.
- **Bedrock provider:** `provider: bedrock` on a profile maps `PLANNER_*` /
  `BUILDER_*` to Bedrock model IDs + region + IAM; the OpenAI-compatible path
  is unchanged. May ship as a documented stub (`S21.bedrock.1`).

Durability stays on Mongo + checkpointer initially; larger artifacts can move
to S3 and managed document DB later.

## 9. Advanced direction (post-baseline, on-rails workflows)

Once the multi-agent baseline works, evolve toward **one LangGraph per
business workflow** (standup follow-up, Jira bulk correction, audit artifact
pack, docs reconciliation, architecture intake) rather than one generic prompt;
**node-level tool scoping** (Stage-10 pattern applied consistently); versioned
**context packs**; explicit **approval contracts** (what/who/expiry/rollback);
a **policy engine** combining Stage-19 RBAC with workflow policy
(`dry_run_only`, connector gates, data classification); and **secure
delegation** (subagents cannot escalate tools, read secrets, or call MCP tools
outside their profile).

## 10. Env surface

Defined in the Stage-21 §21h table in `IMPLEMENT.md` and the global Env-surface
table (`DEEP_AGENT_RUNTIME_MODE`, `DEEP_AGENT_PROFILES_FILE`,
`DEEP_AGENT_DEFAULT_PROVIDER`, `DEEP_AGENT_BEDROCK_REGION`,
`DEEP_AGENT_CHECKPOINT_COLLECTION`, `DEEP_AGENT_RUN_COLLECTION`,
`DEEP_AGENT_ARTIFACT_DIR`, `DEEP_AGENT_REQUIRE_HITL`,
`DEEP_AGENT_DRY_RUN_ONLY`, `DEEP_AGENT_MAX_PARALLEL_RUNS`,
`DEEP_AGENT_PROFILE_TIMEOUT_SECONDS`). They are already reserved in
`compose.yaml` / `.env.example`.

## 11. Verification intent (Stage-21 acceptance)

1. Profile list shows ≥7 agents (Jira, Docs, Audit, Workflow, Auth,
   Architecture, Standup) with **non-overlapping** tool scopes.
2. A Jira agent run produces dry-run ticket edits/creates and pauses at HITL.
3. A Docs agent run suggests a revision and pauses before applying.
4. A Standup agent run consumes session/chat context and emits Jira proposals
   with no live writes.
5. A denied profile/tool call fails closed with a clear policy error
   (recorded as a policy event).
6. Checkpoint/resume works across a container restart.
7. Runtime runs in local compose; ECS/Fargate or K8s blueprint + Bedrock path
   documented or stubbed.
8. Observability exposes logs/metrics and an admin trace UI.

## 12. Task map

`S21.arch.1` (this doc) → `S21.profile.1` (profile schema/config) →
`S21.policy.1` (per-profile allowlist enforcement) + `S21.context.1` (context
packs) → `S21.runtime.1` (runtime API) → `S21.hitl.1` (interrupt/resume) +
`S21.ui.1` (admin UI) → `S21.agent.1` (baseline agents) → `S21.security.1`,
`S21.obs.1`, `S21.deploy.1` → `S21.deploy.2`, `S21.bedrock.1` → `S21.verify.1`,
`S21.verify.2`. See the Stage-21 checklist in `IMPLEMENT.md` for the
authoritative dependency edges.
