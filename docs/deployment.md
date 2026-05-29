# Deep Agent platform — deployment & verification (Stage 21)

This is the operational companion to the design doc
([`deep_agent_platform.md`](deep_agent_platform.md) §10). It covers the three
runtime modes, the container/healthcheck contract, the managed blueprint, and
the **verification checklist** for S21.verify.2 (deployment + restart).

## Runtime modes (`DEEP_AGENT_RUNTIME_MODE`)

| Mode | Where the runtime executes | When to use |
| --- | --- | --- |
| `in_mcp` *(default)* | Inside the `mcp` container | Single-node / compose; the baseline. No extra container. |
| `sidecar` | The optional `sandbox` container | Isolate agent shell/code/fs work + artifact exchange from the request path. Start with `docker compose --profile sandbox up -d`. |
| `remote` | A managed cluster (K8s/ECS) | Production scale-out. See `deploy/k8s/`. |

All three speak the same env/secret contract — nothing is local-only:

- LLM access: `UPSTREAM_BASE_URL` + `UPSTREAM_API_KEY` (or per-role
  `PLANNER_*`/`BUILDER_*`, or `*_PROVIDER=bedrock` with an IAM role — no key).
- State: `MONGO_URL`. Run records (`DEEP_AGENT_RUN_COLLECTION`), the LangGraph
  checkpoint (`LANGGRAPH_CHECKPOINT_COLLECTION`), and the audit trail
  (`DEEP_AGENT_AUDIT_COLLECTION`) all persist there.
- Profiles: `DEEP_AGENT_PROFILES_FILE` (mounted config, reviewable).
- Guardrail: `DEEP_AGENT_DRY_RUN_ONLY=true` blocks any live external write
  regardless of connector gates.

## Healthcheck contract

| Service | Port | Path |
| --- | --- | --- |
| `mcp` | 8080 | `/healthz` |
| `web` | 3000 | `/healthz` |
| `sandbox` (sidecar) | 8090 | `/healthz` |

Compose declares these; the K8s manifests reuse them as readiness/liveness
probes. The `sandbox` sidecar serves a stdlib-only `/healthz` (`sidecar.py`)
that also reports whether the shared artifact dir is writable.

## Managed blueprint

`deploy/k8s/` is the chosen blueprint (plain YAML, no Helm) — namespace, Secret
template, ConfigMap (+ profiles), Mongo StatefulSet, MCP/Web Deployments,
optional sandbox sidecar, Ingress, HPA. ECS/Fargate is the documented
alternative target (task role for Bedrock, Secrets Manager/SSM, CloudWatch
logs, VPC reach to Mongo + connectors) and is blueprint-only at this stage.
See `deploy/k8s/README.md`.

## Observability

- **Logs:** structured single-line `[deep_agent.*] k=v` to stdout/stderr (run
  lifecycle, per-tool timing, audit). Greppable; collect with the platform log
  agent.
- **Metrics:** `agent_metrics` MCP tool / `GET /api/agents/metrics`
  (`?format=prometheus` for the exposition format) — run counts, per-agent
  tool-call/error counts, per-profile latency, recent policy denials.
- **Audit:** every denied (out-of-allowlist) tool call and every HITL approval
  decision (actor + capabilities + decision) is persisted to
  `DEEP_AGENT_AUDIT_COLLECTION`, with secrets redacted.

## Verification checklist (S21.verify.2)

**Compose health**

```bash
docker compose up --build -d
docker compose ps                      # mcp / web / mongo all "healthy"
docker compose --profile sandbox up -d # optional
docker compose exec sandbox curl -s localhost:8090/healthz   # -> {"status":"ok",...}
```

**Platform smoke** — runs the full functional pass (list/route/dry-run/HITL/
fail-closed/persistence/no-live-writes):

```bash
docker compose exec mcp python /app/../scripts/smoke_deep_agent_platform.py
# or from the host: python scripts/smoke_deep_agent_platform.py
```

**Restart drill — pending HITL approval survives a restart** (the core
durability guarantee; run record + checkpoint both in Mongo, not pod memory):

1. Start a write-capable agent run that pauses at `interrupt_on`
   (the smoke suite does this and prints the `run_id`, or use the `/agents` UI).
2. Confirm `agent_run_status` shows `waiting_approval`.
3. Restart the runtime: `docker compose restart mcp` (K8s:
   `kubectl rollout restart deployment/mcp -n sgland`).
4. After it's healthy, `agent_run_status` for the same `run_id` still shows
   `waiting_approval` with the same pending tool/payload.
5. Resume (`agent_run_resume`) succeeds without re-running from scratch.

`scripts/smoke_agent_hitl.py` already automates exactly this restart drill for
the in-mcp path.

**Rollback**

```bash
kubectl rollout undo deployment/mcp -n sgland   # pending approvals unaffected (Mongo-backed)
```
