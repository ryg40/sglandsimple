# Deep Agent platform (Stage 21) — design

> **Status:** design doc for Stage 21 (`S21.arch.1`). Decisions locked
> 2026-05-26: **adopt the LangChain `deepagents` SDK** as the runtime, and
> use **one agent per external system** (read/write gated per-tool, not
> separate reader/writer agents). The code described under "Target
> architecture" is the plan; only the Stage-4 baseline exists today. For the
> Stage-4 primitive, see [`deep_agent.md`](deep_agent.md).

## 1. What this stage is

Stage 4 shipped a single planner→builder subagent pair (`plan_task` /
`run_plan` / `deep_agent`) — **one generic agent with one global tool
catalog**. Any plan can call any non-excluded MCP tool; there is no per-task
scope, no isolated context per subtask, no first-class HITL gate, and no
deployment story beyond "runs inside `mcp`."

Stage 21 turns that into a **platform**: a lightweight **orchestrator** that
routes a goal to one of a small set of **system-specific agents**, each with
(a) a strict tool allowlist, (b) its own — typically **smaller/cheaper** —
model, (c) an isolated context window, and (d) per-tool HITL gates on its
write tools. The orchestrator stays small and just coordinates; the heavy
context lives only inside the subagent that needs it.

The four goals driving every choice below:

1. **Minimize context** — the orchestrator holds routing + a one-line
   description of each agent; each subagent gets only its own
   system_prompt + context pack, in an isolated window.
2. **Use lesser models for execution/research/review** — per-subagent `model`
   override; the orchestrator can run a small router model, subagents run the
   cheapest model that does their job.
3. **Limited, focused access** — each agent's `tools` is an explicit allowlist
   of *its* MCP tools (and the workflows/templates/scripts it drives), nothing
   else. Write tools are individually HITL-gated.
4. **Modular, low-interdependence, extensible** — adding a new app environment
   (WAF, Splunk, Datadog, …) is "write one agent definition + wire its MCP
   tools," with no change to existing agents or the orchestrator routing model.

## 2. SDK decision — adopt `deepagents`

We build on LangChain's **`deepagents`** SDK
(`create_deep_agent(...)`), not a hand-rolled harness, because it provides
exactly the primitives these goals need, on the **LangGraph runtime we already
use** (durable execution, checkpointing, streaming, HITL):

| deepagents primitive | What it gives us | Maps to goal |
| --- | --- | --- |
| `subagents=[...]` (dict or `CompiledSubAgent`) | One definition per system-specific agent | modularity |
| built-in **`task` tool** | Orchestrator delegates to a subagent that runs in an **isolated context window** | minimize context |
| subagent `tools` (`list[Callable]`) — "overrides inherited tools entirely" | Per-agent allowlist of MCP tools | limited access |
| subagent `model` (`str` \| `BaseChatModel`) — "overrides the main agent's model" | Cheaper model per agent | lesser models |
| subagent `system_prompt` — "does not inherit from main agent" | Focused, minimal prompt per agent | minimize context |
| `interrupt_on` (`dict[str, bool]`) | **Per-tool HITL** — gate exactly the write tools | safety |
| subagent `skills` / `middleware` — do not inherit | Versioned context packs, scoped middleware | modularity |
| `CompiledSubAgent(name, description, runnable)` | Wrap an **existing compiled LangGraph** as a subagent | reuse |
| built-in `write_todos` planning + filesystem tools | Orchestrator planning + `/sandbox` artifacts | reuse Stage-4 sandbox |

The `subagent` dict schema we target (verbatim field names): `name`,
`description`, `system_prompt`, `tools`, `model`, `middleware`, `interrupt_on`,
`skills`, `response_format`, `permissions`.

### 2.1 The gating cost — LangChain 1.x upgrade

**`deepagents` 0.6.3 requires `langchain>=1.3.0` and `langchain-core>=1.4.0`.**
We are pinned at `langchain-core==0.3.28`, `langchain-openai==0.2.14`,
`langgraph==0.2.62`, `langgraph-checkpoint-mongodb==0.1.0`. Adoption therefore
requires a **0.3 → 1.x dependency upgrade** that touches every existing graph:
`ask_data`, `docs_agent`, `web_research`, the Stage-4 planner/builder, and the
Mongo checkpointer. This is the single biggest risk in the stage and gets its
own task (`S21.upgrade.1`) ahead of any agent work, with the existing smokes
(`smoke_ask_data.sh`, docs-agent HITL, `smoke_deep_agent.sh`) as the
regression gate. If the upgrade proves too disruptive, the fallback is to keep
the Stage-4 hand-rolled harness and add a per-profile allowlist (the
previous design); that fallback is recorded but **not** the chosen path.

## 3. Relationship to Stage 4 (keep / change)

| Stage-4 piece | File | Disposition under deepagents |
| --- | --- | --- |
| `Plan`/`Step`/`StepResult` models | `deep_agent/models.py` | Keep for the existing `plan_task`/`run_plan` tools; new agents use deepagents' own loop, not `Plan`. Add `RunRecord`/`Proposal`/`ApprovalRequest` typed models. |
| Planner/builder LLM split via `structured(role=)` | `deep_agent/planner.py`, `builder.py`, `mcp/llm.py` | Becomes per-subagent `model`; orchestrator = router model, subagents = cheaper models. The `PLANNER_*`/`BUILDER_*` env seam still feeds model selection. |
| Global tool catalog + `_EXCLUDED` denylist | `deep_agent/catalog.py` | **Superseded** by per-subagent `tools` allowlists. The recursion guard (no agent may call `task`/agent-runtime tools recursively) stays as a floor. |
| Mongo persistence of plans | `deep_agent_plans` | Add `deep_agent_runs` (run metadata/traces/artifacts) + reuse the checkpointer collection for HITL resume. |
| Budget/step/runtime caps | `deep_agent/budget.py` | Per-agent budgets; deepagents middleware can carry them. |
| Sandbox fs/shell tools | Stage-4 sandbox | Reuse via deepagents' built-in filesystem tools pointed at `/sandbox`. |
| `ask_data`, `docs_agent` graphs | `mcp/ask_data.py`, `mcp/docs_agent.py` | **Wrap as `CompiledSubAgent`** — do not rewrite. The mongo agent and docs agent are existing graphs exposed to the orchestrator. **Bridged via `runtime._messages_adapter`** (S21.agent.1): deepagents requires a CompiledSubAgent runnable to consume/return a `messages` key, which `AskDataState`/`DocsAgentState` lack; the adapter is a `MessagesState`-in/out graph that lifts the delegated task text, runs the native `run_ask_data`/`run_docs_agent`, and returns the result as an `AIMessage`. Without it the orchestrator→graph delegation hangs at `running`. |

The existing `plan_task`/`run_plan`/`deep_agent` MCP tools remain for backward
compatibility; the new platform is additive.

## 4. Agent roster (one per system, read/write gated per-tool)

The orchestrator is a thin router. Below it, one agent per system; each agent's
**write tools** are listed under `interrupt_on` (HITL) and respect
`write_policy` + the existing connector write gates. Read-only agents have no
`interrupt_on` entries and a `read_only` policy.

| Agent | Model tier | Tools (allowlist) | Write policy | HITL (`interrupt_on`) |
| --- | --- | --- | --- | --- |
| **orchestrator** | small router | `task` (delegate only) + `write_todos` | n/a (no external writes) | — |
| **atlassian_agent** | mid | `jira_stage_edits`, `jira_validate_staged`, `jira_revert_staged`, `jira_apply_staged`, Confluence read + `confluence_update_page`, `docs_search` | dry_run_only | `jira_apply_staged`, `confluence_update_page` |
| **mongo_agent** | small/mid | `CompiledSubAgent` wrapping `ask_data` (read-only via `validate_spec`) + `mongo_query` reads | read_only | — |
| **github_agent** | mid | GitHub read (PR/review context) + review-comment + deploy-trigger tools | dry_run_only | deploy/merge tools |
| **servicenow_agent** | small/mid | ServiceNow read (incidents/changes) + record-write tools | dry_run_only | record-write tools |
| **aws_agent** | small/mid | AWS *describe*/read via AWS MCP connector (no mutate) | read_only | — |
| **audit_agent** | mid | report tools + Archer/SNOW/Snowflake/Mongo **reads** + `docs_search` | dry_run_only | Archer update |
| **docs_agent** | mid | `CompiledSubAgent` wrapping the Stage-14 docs agent (`docs_*`, `docs_sync`) | dry_run_only | doc apply / `docs_sync` live |
| **standup_agent** | mid | standup session data + Jira/docs templates (reuse `mcp/standup_agent.py`) | dry_run_only | proposal apply |

Notes on the user's read/write instinct: rather than a `servicenow_reader` +
`servicenow_writer` pair, ServiceNow is **one** `servicenow_agent` whose write
tools are the only ones in its `interrupt_on` set and gated by
`write_policy=dry_run_only` + `CONN_SERVICENOW_ENABLED`/`WORKFLOW_WRITES_ENABLED`.
Same identity, same context pack, write path behind HITL — fewer agents, same
least-privilege boundary. (If a future system needs hard credential separation
between read and write, the roster table is the one place that changes.)

### 4.1 Extensibility — adding WAF / Splunk / Datadog later

A new environment is a new row: write `{name, description, system_prompt,
tools: [<that system's MCP tools>], model, interrupt_on, skills}` and register
it in `profiles.yaml`. No existing agent changes; the orchestrator picks it up
from its `description`. This is the modularity goal made concrete — the roster
is data, not code branches.

## 5. Profile config

Agents are declared in `profiles.yaml` (loaded + validated at startup; invalid
profiles fail fast) and compiled into deepagents `subagents`:

```yaml
- name: servicenow_agent
  description: Read ServiceNow incidents/changes; stage record writes (HITL).
  model: "openai:<small-mid-model>"
  allowed_tools: [servicenow_search, servicenow_get, servicenow_update_record]
  write_tools:   [servicenow_update_record]   # -> interrupt_on + write_policy
  write_policy:  dry_run_only                  # read_only | dry_run_only | write_capable
  required_capability: canUpdateArcher         # Stage-19 gate (nullable)
  context_packs: [servicenow_basics]
  budget_tokens: 40000
  max_steps: 15
```

The loader translates each profile into a deepagents subagent dict
(`tools`=resolved MCP callables for `allowed_tools`, `interrupt_on`={t: True
for t in write_tools}, `model`, `system_prompt`=template+context pack). Existing
graphs (`ask_data`, `docs_agent`) are emitted as `CompiledSubAgent` instead.

## 6. Context packs

Per-agent, versioned bundles (`deep_agent/context.py`) of templates / schemas /
examples / runbook links, sourced from existing material (Stage-9 Jira
template, `mcp/standup_agent.py` story context, Stage-14 `docs_*`, Stage-18
inventory template). Mapped onto the subagent `skills` field where it fits.
Keeps each subagent's prompt minimal — only its own pack, never the whole
corpus.

## 7. HITL interrupt/resume

Implemented (`S21.hitl.1`) on deepagents' `interrupt_on` per-tool pauses, backed
by the Mongo LangGraph checkpointer (the same mechanism the Stage-14 docs agent
proved). Concretely:

- **Interrupt shape.** deepagents wires `interrupt_on={tool: True}` through
  `HumanInTheLoopMiddleware`, which interrupts with a `HITLRequest`
  (`{action_requests: [{name, args, description}], review_configs: [...]}`).
  `runtime._extract_interrupt` parses the first pending action into a typed
  `ApprovalRequest` (`tool`, `payload` = the tool args, `rationale` = the
  description) and resolves `required_capability` from the **owning agent
  profile's** `write_tools`/`required_capability` (so the gate follows the tool,
  not the routing).
- **Resume contract.** `agent_run_resume({run_id, decision, actor,
  actor_capabilities})` translates the high-level decision (`approve` /
  `reject` / edited args) into the middleware's required
  `{"decisions": [Decision, …]}` payload — **one decision per pending
  `action_request`** — and resumes via `Command(resume=…)`.
- **Capability gate.** Approving or editing a capability-gated write requires
  `actor_capabilities` to include the agent's `required_capability`; otherwise a
  `PermissionDeniedError` is raised (the web proxy maps it to HTTP 403). A
  *reject* needs no capability.
- **Dry-run guardrail.** When `DEEP_AGENT_DRY_RUN_ONLY` is on, an approve/edit is
  downgraded to a no-write reject so no write tool executes; the run resolves as
  `rejected` with a clear reason. Write tools also keep their own
  `*_WRITES_ENABLED` gate downstream.
- **Restart durability.** The run record (`deep_agent_runs`) and the graph
  checkpoint (`lg_checkpoints`) are both in Mongo, so a paused approval survives
  an MCP restart and remains resumable (verified — see
  `scripts/smoke_agent_hitl.py` and `S21.verify.2`).

## 8. Runtime API

MCP tools + `web/main.py` `/api/agents/*` proxies (typed; no `any` on the TS
side), shared by web/MCP/background callers:

`agent_profiles_list`, `agent_run_start` `{agent?, goal, context_refs, mode}`
(omit `agent` to let the orchestrator route), `agent_run_status`,
`agent_run_resume`, `agent_run_cancel`, `agent_run_artifacts`.

`agent_run_start` is intentionally **non-blocking**: it persists a `running`
record in `DEEP_AGENT_RUN_COLLECTION`, launches the LangGraph/deepagents
orchestrator in the background, and returns a pollable `run_id`. Clients poll
`agent_run_status` until the run reaches `completed`, `error`, `cancelled`, or
`waiting_approval`.

## 9. Security, audit, observability

Per-run `actor`/`source`/agent/role-capability-snapshot/correlation-id;
tool I/O persisted with secret **redaction**; denied tool calls persisted as
policy events; approvals record actor/groups/roles/original+edited
payload/validation/apply result; structured logs + a metrics surface (active/
completed/failed runs, pending approvals, token usage, tool-call counts,
per-agent latency); `/agents` operations route (`canRunWorkflow`-gated) for
profiles, starting dry-run runs, status/artifacts, pending approvals,
resume/cancel.

## 10. Deployment

`DEEP_AGENT_RUNTIME_MODE`: `in_mcp` (default/baseline — code in the `mcp`
container), `sidecar` (the `sandbox` container), `remote` (ECS/Fargate or
K8s). The optional `sandbox` service (`sandbox-runtime/`, added in
`S21.upgrade.1`) already exists as the isolated, non-root sidecar shell — gated
behind the `sandbox` compose profile so it's off by default
(`docker compose --profile sandbox up -d`); it shares the `./sandbox` mount with
`mcp` and idles until `S21.deploy.1` gives it the runtime entrypoint. Managed blueprints (≥1 in this stage): ECS/Fargate (task role, Secrets
Manager/SSM, CloudWatch, VPC reach to Mongo + connectors) or K8s
(Helm/Kustomize, config maps for profiles, HPA on concurrent runs). Optional
`provider: bedrock` per agent maps model selection to Bedrock IDs + IAM; the
OpenAI-compatible path is unchanged (may ship stubbed).

## 11. Env surface

Stage-21 §21h table in `IMPLEMENT.md` + the global Env-surface table
(`DEEP_AGENT_RUNTIME_MODE`, `DEEP_AGENT_PROFILES_FILE`,
`DEEP_AGENT_DEFAULT_PROVIDER`, `DEEP_AGENT_BEDROCK_REGION`,
`DEEP_AGENT_CHECKPOINT_COLLECTION`, `DEEP_AGENT_RUN_COLLECTION`,
`DEEP_AGENT_ARTIFACT_DIR`, `DEEP_AGENT_REQUIRE_HITL`, `DEEP_AGENT_DRY_RUN_ONLY`,
`DEEP_AGENT_MAX_PARALLEL_RUNS`, `DEEP_AGENT_PROFILE_TIMEOUT_SECONDS`). Already
reserved in `compose.yaml`/`.env.example`.

## 12. Verification intent

1. Profile list shows the orchestrator + system agents (Atlassian, Mongo,
   GitHub, ServiceNow, AWS, Audit, Docs, Standup) with **non-overlapping** tool
   scopes.
2. Orchestrator routes a goal to the right agent via the `task` tool; the
   subagent runs in an isolated context.
3. Atlassian agent produces dry-run Jira edits and pauses at `interrupt_on`.
4. Mongo agent answers a read-only query (no writes possible).
5. A denied tool call (outside an agent's allowlist) fails closed + is recorded.
6. Checkpoint/resume survives container restart.
7. Runs in local compose; ECS/Fargate or K8s blueprint + Bedrock path
   documented or stubbed.
8. Observability exposes logs/metrics + admin trace UI.
9. A new stub agent (e.g. a Datadog/Splunk read agent) can be added by config
   alone, proving the extensibility path.

## 13. Task map

`S21.arch.1` (this doc) → `S21.upgrade.1` (LangChain 1.x + deepagents install,
existing smokes green) → `S21.profile.1` (profile schema/loader →
deepagents subagents) → `S21.context.1` (context packs) → `S21.orch.1`
(`create_deep_agent` orchestrator + `task` routing) → `S21.runtime.1`
(`agent_run_*` API) → `S21.hitl.1` (`interrupt_on` resume) + `S21.ui.1` (admin
UI) → `S21.agent.1` (baseline system agents, incl. `ask_data`/`docs_agent` as
`CompiledSubAgent`) → `S21.security.1`, `S21.obs.1`, `S21.deploy.1` →
`S21.deploy.2`, `S21.bedrock.1` → `S21.verify.1`, `S21.verify.2`. The Stage-21
checklist in `IMPLEMENT.md` is authoritative for dependency edges.

## 14. Why each decision — a contributor's guide

> This section exists because the platform is meant to be **extended by people
> of varied experience levels**. If you are here to add a new agent (WAF,
> Splunk, Datadog, a new workflow) you should be able to copy a pattern and
> understand *why* it's shaped that way. Each decision below states the choice,
> the reason, and what you do with it as a contributor.

### Platform-level decisions

- **Adopt `deepagents` instead of hand-rolling.** *Why:* the delegation
  (`task`), isolated subagent context, per-subagent `tools`/`model`, and
  per-tool HITL (`interrupt_on`) are exactly our four goals, already built and
  maintained upstream on the LangGraph runtime we use. Hand-rolling them is
  surface area we'd own forever. *Contributor takeaway:* you define agents as
  **data** (a dict / YAML row), not by writing graph code — that's what keeps
  the barrier to adding an agent low.

- **One agent per system, write tools gated per-tool — not separate
  reader/writer agents.** *Why:* a reader/writer split doubles the agent count
  and the routing decisions for a safety boundary that `interrupt_on` +
  `write_policy` already give you inside one agent. Fewer agents = less to learn
  and less to break. *Contributor takeaway:* put a system's read and write tools
  in one agent; list only the **write** tools under `interrupt_on`. Reach for a
  separate writer agent **only** if a system needs hard credential separation
  (note it in the roster table — the one place that decision lives).

- **A thin orchestrator that only routes.** *Why:* if the orchestrator held
  tools or domain context, every task would pay for context it doesn't use, and
  routing logic would tangle with execution logic. Keeping it to `task` +
  `write_todos` means the expensive context lives only in the one subagent that
  needs it (the "minimize context" goal, made structural). *Contributor
  takeaway:* never add a system tool to the orchestrator; add it to a subagent
  and let the orchestrator route by the subagent's `description`. **The
  `description` is load-bearing** — write it as "when to delegate here," because
  that string is the entire basis on which routing happens.

- **Cheaper model per subagent.** *Why:* a ServiceNow read or an AWS describe
  doesn't need the frontier model; paying for it on every step is the most
  common silent cost in multi-agent systems. *Contributor takeaway:* start a
  new agent on the **smallest** model that passes its smoke; only raise the tier
  if its outputs are actually wrong. The orchestrator router can be small too —
  routing is a classification task.

- **Wrap existing graphs as `CompiledSubAgent` rather than rewriting.** *Why:*
  `ask_data` and `docs_agent` are tested, HITL-correct LangGraph workflows.
  Rewriting them as prompt-driven subagents would discard that and risk
  regressions. *Contributor takeaway:* if your "agent" is really a fixed,
  multi-step procedure (not open-ended tool use), build it as a compiled
  LangGraph and register it as a `CompiledSubAgent` — it's more reliable and
  cheaper than a free-form agent for on-rails work.

- **Profiles in `profiles.yaml`, validated at startup.** *Why:* config-as-data
  means a non-expert can add an agent without touching Python, and a malformed
  profile fails loudly at boot instead of mid-run. *Contributor takeaway:* this
  file is your main entry point — adding an environment is usually a new YAML
  row plus wiring its MCP tools.

- **The LangChain 1.x upgrade is its own task, gated by existing smokes.**
  *Why:* `deepagents` forces a dependency jump that touches every existing
  graph; bundling it with feature work would make a failure impossible to
  bisect. *Contributor takeaway:* don't start agent work until `S21.upgrade.1`
  is green — building on a half-migrated base wastes your time.

### Per-agent justifications

Each agent is scoped to *one system's vocabulary and credentials* so its prompt
stays small, its blast radius is one system, and its tools can't be confused
with another's. Read-only by default; writes behind HITL.

- **orchestrator** — exists so subagents never need to know about each other;
  routing is centralized and cheap. Holds no system tools by design.
- **atlassian_agent** — Jira + Confluence are one Atlassian credential/domain
  and frequently move together (a story and its doc), so one agent; `apply` and
  `confluence_update_page` are the only HITL tools because everything else is
  staging/reads.
- **mongo_agent** — wraps `ask_data`, which is already read-only via
  `validate_spec`; no write path means **no HITL needed**, which is the cheapest
  and safest shape. Models the "data access is read-only and least-privilege" rule.
- **github_agent** — code review (read + comment) and deploy/merge are different
  risk levels, so deploy/merge are the HITL tools while review context is free.
- **servicenow_agent** — the worked example of "one agent, write tool gated"
  that replaces the user's reader/writer instinct; read is free, record writes
  pause for approval.
- **aws_agent** — describe/read only against the AWS MCP; deliberately *no*
  mutation tools, so it's a pure read agent (the template for future
  observability agents like Datadog/Splunk).
- **audit_agent** — spans several systems but **reads** them to assemble
  evidence; only Archer updates write, behind HITL — shows how a cross-system
  agent stays safe by being read-mostly.
- **docs_agent / standup_agent** — reuse existing Stage-14/Stage-20 logic as
  subagents so the platform composes prior work instead of forking it.

### The recipe for a new agent (e.g. WAF, Splunk, Datadog)

1. Add the system's MCP tools (or a connector) — read tools first.
2. Add a `profiles.yaml` row: `name`, a **delegation-oriented** `description`,
   the smallest viable `model`, `allowed_tools`, `write_tools` (→ `interrupt_on`),
   `write_policy`, `required_capability`, and a small `context_pack`.
3. Start `read_only`. Add write tools only when needed, and always list them in
   `write_tools` so they're HITL-gated.
4. Add a one-goal smoke. No orchestrator or other-agent changes required — that
   no-other-changes property is the whole point of the architecture.
