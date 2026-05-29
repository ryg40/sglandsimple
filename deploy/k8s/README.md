# Deep Agent platform — Kubernetes deployment blueprint (S21.deploy.2)

This directory is the **chosen managed-runtime blueprint** for the Deep Agent
platform. It deploys the same containers the compose stack runs (`mcp`, `web`,
optional `sandbox` sidecar) onto Kubernetes, with the runtime in
`DEEP_AGENT_RUNTIME_MODE=in_mcp` by default (the sidecar manifest covers
`sidecar` mode). ECS/Fargate is documented as the alternative target in
[`docs/deep_agent_platform.md` §10](../../docs/deep_agent_platform.md) and is
left as a blueprint-only path per the stage scope.

> These manifests are a **blueprint** — image references (`REGISTRY/...`),
> hostnames, and storage classes are placeholders. Build/push the `mcp` and
> `web` images, then `sed`/Kustomize the registry in. They are intentionally
> plain YAML (no Helm) so the moving parts are visible.

## What's here

| File | Covers |
| --- | --- |
| `namespace.yaml` | `sgland` namespace |
| `secret.example.yaml` | Secret **template** — upstream LLM key, Mongo creds, auth. Never commit a filled copy. |
| `configmap.yaml` | Non-secret env (runtime mode, collections, dry-run guardrail) + the agent `profiles.yaml` mounted into `mcp`. |
| `mongo.yaml` | StatefulSet + headless Service + PVC for Mongo (the checkpoint/run/audit store). |
| `mcp-deployment.yaml` | MCP Deployment + Service. Runtime container; `readinessProbe`/`livenessProbe` on `/healthz`; task identity via ServiceAccount (for Bedrock IRSA). |
| `web-deployment.yaml` | Web Deployment + Service + Ingress. |
| `sandbox-deployment.yaml` | Optional sidecar runtime (`DEEP_AGENT_RUNTIME_MODE=sidecar`); non-root, `/healthz` probe. |
| `hpa.yaml` | HorizontalPodAutoscaler on the MCP deployment. |

## Deploy order

```bash
kubectl apply -f namespace.yaml
# fill secret.example.yaml -> secret.yaml (gitignored) first:
kubectl apply -f secret.yaml
kubectl apply -f configmap.yaml
kubectl apply -f mongo.yaml
kubectl rollout status statefulset/mongo -n sgland
kubectl apply -f mcp-deployment.yaml
kubectl apply -f web-deployment.yaml
# optional sidecar runtime:
kubectl apply -f sandbox-deployment.yaml
kubectl apply -f hpa.yaml
```

## Secrets & config

- **No API keys in env files.** Upstream LLM key + Mongo creds + auth secret
  live in the `sgland-secrets` Secret (mounted as env). For **Bedrock**
  (`*_PROVIDER=bedrock`) there is **no key** — bind an IAM role to the
  `mcp` ServiceAccount via IRSA (EKS) / Workload Identity (GKE) granting
  `bedrock:InvokeModel` + `bedrock:InvokeModelWithResponseStream`. See
  `mcp-deployment.yaml` annotations.
- The agent `profiles.yaml` is delivered as a ConfigMap and mounted at
  `DEEP_AGENT_PROFILES_FILE` so scopes are reviewable/auditable in-cluster.

## Healthchecks

Every workload exposes `/healthz`: `mcp` :8080, `web` :3000, `sandbox` :8090.
The probes here gate rollouts and back the autoscaler. This is the same
contract the compose healthchecks use, so the verification checklist in
[`docs/deployment.md`](../../docs/deployment.md) applies to both.

## Scaling & rollback

- **Scaling:** `hpa.yaml` scales `mcp` on CPU; for run-concurrency-based scaling
  scrape `deep_agent_runs_started_total` / `deep_agent_run_latency_seconds_avg`
  from `agent_metrics` (`format=prometheus`) and drive a custom-metrics HPA.
- **Rollback:** `kubectl rollout undo deployment/mcp -n sgland`. Pending HITL
  approvals survive a pod restart because the run record **and** the LangGraph
  checkpoint both live in Mongo (not pod memory) — see the restart drill in
  `docs/deployment.md`.

## Logs

`mcp` emits structured single-line `[deep_agent.*] k=v` logs (run lifecycle,
tool calls, audit) to stdout/stderr → collect with the cluster log agent
(Fluent Bit / CloudWatch / Loki). Metrics: scrape `/api/agents/metrics?format=prometheus`.
