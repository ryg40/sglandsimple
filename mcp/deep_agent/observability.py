"""Deep Agent platform observability + security (S21.obs.1 / S21.security.1).

Two concerns, one module because they share the same dispatch seam:

* **Observability** — in-process metrics counters + structured single-line logs
  covering run lifecycle (active/completed/failed/cancelled), pending
  approvals, per-profile latency, tool-call counts, and token budgets. The
  counters are exposed through ``metrics_snapshot()`` (consumed by the
  ``agent_metrics`` MCP tool / ``/api/agents/metrics`` proxy) and a
  Prometheus-style text rendering via ``metrics_prometheus()``.

* **Security** — secret redaction for tool inputs/outputs (``redact``), a
  persisted **policy audit trail** (denied tool calls, approvals with
  actor/capabilities, policy-flag decisions) written to
  ``DEEP_AGENT_AUDIT_COLLECTION`` and mirrored to an in-process ring so the
  boundary is observable without the DB, and the ``read_only`` /
  ``dry_run_only`` / ``write_capable`` policy-flag helpers.

Logging follows the ``budget.py`` convention: one ``[deep_agent.<area>] k=v``
line per event, flushed, so ``docker compose logs mcp`` stays greppable.
"""

from __future__ import annotations

import os
import re
import sys
import time
from collections import defaultdict
from typing import Any

# ---------------------------------------------------------------------------
# Structured logging
# ---------------------------------------------------------------------------


def log_event(area: str, **fields: Any) -> None:
    """Emit one structured single-line log (greppable, flushed).

    Mirrors ``deep_agent.budget.log_event`` so all platform logs share a
    format: ``[deep_agent.<area>] k=v k=v ...``. Values with spaces are
    quoted; ``None`` fields are dropped.
    """
    bits = []
    for k, v in fields.items():
        if v is None:
            continue
        s = str(v)
        if " " in s or "=" in s:
            s = '"' + s.replace('"', "'") + '"'
        bits.append(f"{k}={s}")
    print(f"[deep_agent.{area}] " + " ".join(bits), file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Metrics — in-process counters/gauges/histograms
# ---------------------------------------------------------------------------

_COUNTERS: dict[str, float] = defaultdict(float)
# Per-profile latency: name -> {count, total_seconds, max_seconds}
_LATENCY: dict[str, dict[str, float]] = defaultdict(lambda: {"count": 0.0, "total_seconds": 0.0, "max_seconds": 0.0})
_STARTED_AT = time.time()


def incr(name: str, value: float = 1.0, **labels: str) -> None:
    """Increment a counter, optionally keyed by a single label set.

    Labels are folded into the key (``runs_total{agent=mongo_agent}``) so the
    snapshot can break counts down without a real metrics backend.
    """
    _COUNTERS[_key(name, labels)] += value


def observe_latency(agent: str, seconds: float) -> None:
    h = _LATENCY[agent or "(orchestrator)"]
    h["count"] += 1
    h["total_seconds"] += seconds
    h["max_seconds"] = max(h["max_seconds"], seconds)


def _key(name: str, labels: dict[str, str]) -> str:
    if not labels:
        return name
    inner = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
    return f"{name}{{{inner}}}"


def metrics_snapshot() -> dict[str, Any]:
    """Structured snapshot of all counters + per-profile latency.

    Pure data (JSON-serializable) so the MCP tool / web proxy can return it
    directly. ``uptime_seconds`` lets a scraper compute rates.
    """
    latency = {}
    for agent, h in _LATENCY.items():
        cnt = h["count"] or 1
        latency[agent] = {
            "count": int(h["count"]),
            "total_seconds": round(h["total_seconds"], 3),
            "avg_seconds": round(h["total_seconds"] / cnt, 3),
            "max_seconds": round(h["max_seconds"], 3),
        }
    return {
        "uptime_seconds": round(time.time() - _STARTED_AT, 1),
        "counters": {k: (int(v) if v.is_integer() else round(v, 3)) for k, v in sorted(_COUNTERS.items())},
        "latency_by_agent": latency,
    }


_PROM_NAME = re.compile(r"\{.*\}$")


def metrics_prometheus() -> str:
    """Render the snapshot as Prometheus text exposition format.

    Counter keys already carry ``{label=value}`` suffixes from ``incr``; we
    split the base metric name from the label block so a scraper sees proper
    ``deep_agent_runs_total{agent="mongo_agent"} 3`` lines.
    """
    lines: list[str] = []
    lines.append("# HELP deep_agent_uptime_seconds Seconds since runtime metrics started.")
    lines.append("# TYPE deep_agent_uptime_seconds gauge")
    lines.append(f"deep_agent_uptime_seconds {round(time.time() - _STARTED_AT, 1)}")
    for key, val in sorted(_COUNTERS.items()):
        m = _PROM_NAME.search(key)
        if m:
            base = key[: m.start()]
            raw_labels = m.group(0)[1:-1]
            # quote label values: agent=mongo -> agent="mongo"
            labels = ",".join(
                f'{k}="{v}"' for k, _, v in (p.partition("=") for p in raw_labels.split(",") if p)
            )
            rendered = f"deep_agent_{base}{{{labels}}}"
        else:
            base = key
            rendered = f"deep_agent_{key}"
        lines.append(f"# TYPE deep_agent_{base} counter")
        lines.append(f"{rendered} {int(val) if float(val).is_integer() else val}")
    for agent, h in _LATENCY.items():
        safe = re.sub(r"[^a-zA-Z0-9_]", "_", agent)
        cnt = h["count"] or 1
        lines.append(f'deep_agent_run_latency_seconds_avg{{agent="{safe}"}} {round(h["total_seconds"] / cnt, 3)}')
        lines.append(f'deep_agent_run_latency_seconds_max{{agent="{safe}"}} {round(h["max_seconds"], 3)}')
    return "\n".join(lines) + "\n"


def reset_metrics() -> None:
    """Test helper — clear all counters/latency."""
    _COUNTERS.clear()
    _LATENCY.clear()


# ---------------------------------------------------------------------------
# Secret redaction
# ---------------------------------------------------------------------------

# Field names whose values are always masked regardless of content.
_SECRET_KEYS = re.compile(
    r"(api[_-]?key|secret|token|password|passwd|pwd|authorization|auth|bearer|"
    r"credential|private[_-]?key|access[_-]?key|session)",
    re.IGNORECASE,
)

# Value patterns that look like secrets even under an innocuous key.
_SECRET_VALUE_PATTERNS = [
    re.compile(r"ghu_[A-Za-z0-9]{20,}"),            # GitHub user-to-server token
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),       # other GitHub tokens
    re.compile(r"sk-[A-Za-z0-9]{16,}"),              # OpenAI-style key
    re.compile(r"AKIA[0-9A-Z]{16}"),                 # AWS access key id
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{6,}"),  # JWT
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]{16,}"),  # bearer header
]

_MASK = "***redacted***"
_MAX_STR = 4000  # cap any single string we persist/log so a runaway tool output can't bloat the audit


def _redact_str(s: str) -> str:
    for pat in _SECRET_VALUE_PATTERNS:
        s = pat.sub(_MASK, s)
    if len(s) > _MAX_STR:
        s = s[:_MAX_STR] + f"…(+{len(s) - _MAX_STR} chars truncated)"
    return s


def redact(value: Any) -> Any:
    """Recursively redact secrets from a tool input/output value.

    - Any dict key matching ``_SECRET_KEYS`` has its value masked outright.
    - String values are scanned for token-shaped substrings and truncated to a
      sane cap. Lists/tuples/dicts recurse. Other scalars pass through.
    """
    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        for k, v in value.items():
            if isinstance(k, str) and _SECRET_KEYS.search(k):
                out[k] = _MASK
            else:
                out[k] = redact(v)
        return out
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return _redact_str(value)
    return value


# ---------------------------------------------------------------------------
# Policy audit trail
# ---------------------------------------------------------------------------

_AUDIT_COLLECTION = os.environ.get("DEEP_AGENT_AUDIT_COLLECTION", "deep_agent_audit")
# In-process ring so the boundary is observable/testable without the DB. Bounded
# so a long-lived process doesn't grow unbounded; the DB holds the durable copy.
_AUDIT_RING: list[dict[str, Any]] = []
_AUDIT_RING_MAX = 500


def _ring_append(event: dict[str, Any]) -> None:
    _AUDIT_RING.append(event)
    if len(_AUDIT_RING) > _AUDIT_RING_MAX:
        del _AUDIT_RING[: len(_AUDIT_RING) - _AUDIT_RING_MAX]


def audit_events(limit: int = 100, kind: str | None = None) -> list[dict[str, Any]]:
    """Most-recent audit events from the in-process ring (newest last)."""
    rows = [e for e in _AUDIT_RING if kind is None or e.get("kind") == kind]
    return rows[-limit:]


async def record_audit(
    kind: str,
    *,
    run_id: str = "",
    agent: str = "",
    tool: str = "",
    actor: str | None = None,
    actor_capabilities: list[str] | None = None,
    reason: str = "",
    detail: dict[str, Any] | None = None,
) -> None:
    """Append one audit event to the ring and (best-effort) persist to Mongo.

    ``kind`` is one of: ``policy_denied`` (out-of-allowlist tool call),
    ``approval`` (a HITL approve/edit/reject decision), ``policy_flag``
    (read_only/dry_run downgrade). ``detail`` is redacted before storage so a
    captured tool payload never leaks a secret into the audit log.
    """
    event = {
        "kind": kind,
        "run_id": run_id,
        "agent": agent,
        "tool": tool,
        "actor": actor,
        "actor_capabilities": list(actor_capabilities or []),
        "reason": reason,
        "detail": redact(detail or {}),
        "ts": time.time(),
    }
    _ring_append(event)
    log_event("audit", kind=kind, run_id=run_id or None, agent=agent or None, tool=tool or None,
              actor=actor, reason=reason or None)
    incr("audit_events_total", **{"kind": kind})
    try:
        from db import get_db

        await get_db()[_AUDIT_COLLECTION].insert_one(dict(event))
    except Exception as e:  # noqa: BLE001 — audit must never break the run
        log_event("audit", kind="persist_failed", error=f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Policy-flag helpers
# ---------------------------------------------------------------------------


def dry_run_only() -> bool:
    """Global guardrail: when on, no approve/edit reaches a live write tool."""
    return os.environ.get("DEEP_AGENT_DRY_RUN_ONLY", "true").lower() == "true"


def policy_flags_for(profile: Any) -> dict[str, bool]:
    """Resolve the three policy flags for an agent profile.

    - ``read_only``    — the profile declares no write tools.
    - ``write_capable``— it has write tools (gated by HITL + capability).
    - ``dry_run_only`` — the global guardrail is on, so even an approval is a
      no-op write for this run.
    """
    has_writes = bool(getattr(profile, "write_tools", None))
    return {
        "read_only": not has_writes,
        "write_capable": has_writes,
        "dry_run_only": dry_run_only(),
    }
