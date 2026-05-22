"""Stage 11 — Compliance command-center overview aggregation.

`overview_summary` rolls up the Stage-9 compliance collections plus the
connector registry into a single payload the Overview page renders in one
polled round-trip:

    { kpis, attention[], connectors[], tables{ findings, epics, work_items, pr_records } }

All reads go through the raw motor db (read-only); the attention rules in 11c
are evaluated server-side. No external calls beyond connector health/summary,
which already degrade gracefully when a connector is disabled.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import db as dbmod
from connectors import list_connectors

# Tunables (11f) — all defaulted.
DUE_SOON_DAYS = int(os.environ.get("OVERVIEW_DUE_SOON_DAYS", "14"))
STALE_DAYS = int(os.environ.get("OVERVIEW_STALE_DAYS", "7"))
ATTENTION_LIMIT = int(os.environ.get("OVERVIEW_ATTENTION_LIMIT", "10"))
TABLE_ROWS = int(os.environ.get("OVERVIEW_TABLE_ROWS", "5"))

_DONE_STATUSES = {"done", "closed", "resolved", "merged", "complete", "completed", "archived"}
_HOT_PRIORITIES = {"high", "critical"}
_HOT_SEVERITIES = {"high", "critical"}

# Reason → rank for ordering the attention list (lower = higher priority).
_REASON_RANK = {
    "overdue": 0,
    "due_soon": 1,
    "prioritized": 2,
    "high_severity": 3,
    "blocked_pr": 4,
    "stalled": 5,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _connector_line(summary: dict[str, Any]) -> str:
    """Derive a one-line health caption from a connector's structured summary."""
    if not isinstance(summary, dict):
        return ""
    if summary.get("summary"):
        return str(summary["summary"])
    # Pick the small scalar count fields (skip bulky sample_data / schema).
    parts: list[str] = []
    for k, v in summary.items():
        if k in ("status", "schema", "sample_data") or isinstance(v, (list, dict)):
            continue
        parts.append(f"{k.replace('_', ' ')}: {v}")
    return " · ".join(parts[:3])


def _parse_dt(value: Any) -> datetime | None:
    """Best-effort parse of a Mongo date / ISO string into an aware datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _is_done(status: Any) -> bool:
    return str(status or "").lower() in _DONE_STATUSES


async def _read(collection: str, *, sort_field: str = "updated_at", limit: int = 200) -> list[dict[str, Any]]:
    db = dbmod.get_db()
    cur = db[collection].find({}).sort(sort_field, -1).limit(limit)
    rows = await cur.to_list(length=limit)
    return [dbmod._stringify_ids(r) for r in rows]


def _days_until(due: datetime | None, ref: datetime) -> float | None:
    if due is None:
        return None
    return (due - ref).total_seconds() / 86400.0


def _attention_for_row(
    row: dict[str, Any],
    kind: str,
    ref: datetime,
) -> list[dict[str, Any]]:
    """Evaluate the 11c rules for a single row; return zero or more items.

    A row may earn multiple reasons; we keep the highest-ranked one per row so
    the panel isn't dominated by a single noisy record.
    """
    # For PR records the canonical field is "state" (GitHub semantics); other collections
    # only carry "status".  Use the same state-first priority as the KPI counter so both
    # agree on what counts as closed/merged.
    status = row.get("state") or row.get("status")
    if _is_done(status):
        return []

    title = row.get("title") or row.get("summary") or row.get("requirement") or row.get("jira_key") or str(row.get("_id"))
    priority = str(row.get("priority") or "").lower()
    severity = str(row.get("severity") or "").lower()
    due = _parse_dt(row.get("due_date"))
    days = _days_until(due, ref)
    updated = _parse_dt(row.get("updated_at"))
    stale_days = _days_until(updated, ref)  # negative = N days ago

    reasons: list[str] = []
    if days is not None and days < 0:
        reasons.append("overdue")
    if days is not None and 0 <= days <= DUE_SOON_DAYS:
        reasons.append("due_soon")
    if kind in ("epic", "finding") and priority in _HOT_PRIORITIES:
        reasons.append("prioritized")
    if kind == "finding" and severity in _HOT_SEVERITIES and str(status or "").lower() == "open":
        reasons.append("high_severity")
    if kind == "pr":
        checks = row.get("checks") or []
        if any(str(c.get("status", "")).lower() in ("failure", "failed", "error") for c in checks if isinstance(c, dict)):
            reasons.append("blocked_pr")
    if kind in ("work_item", "pr") and stale_days is not None and -stale_days >= STALE_DAYS:
        reasons.append("stalled")

    if not reasons:
        return []

    # Keep the single highest-ranked reason for this row.
    reason = min(reasons, key=lambda r: _REASON_RANK.get(r, 99))
    item = {
        "id": str(row.get("_id")),
        "kind": kind,
        "title": title,
        "reason": reason,
        "severity": severity or None,
        "priority": priority or None,
        "due_date": due.isoformat() if due else None,
        "days_until_due": round(days, 1) if days is not None else None,
        "link": f"/hub?kind={kind}&id={row.get('_id')}",
    }
    return [item]


def _rank_key(item: dict[str, Any]) -> tuple[int, float, int]:
    rank = _REASON_RANK.get(item["reason"], 99)
    # Tiebreak: sooner due first; then hotter priority/severity.
    due = item.get("days_until_due")
    due_key = due if due is not None else 9999.0
    hot = item.get("priority") in _HOT_PRIORITIES or item.get("severity") in _HOT_SEVERITIES
    return (rank, due_key, 0 if hot else 1)


async def build_overview() -> dict[str, Any]:
    ref = _now()

    findings = await _read("audit_findings")
    epics = await _read("epics")
    work_items = await _read("work_items")
    pr_records = await _read("pr_records")

    # --- attention list (11c) ---
    attention: list[dict[str, Any]] = []
    for r in findings:
        attention += _attention_for_row(r, "finding", ref)
    for r in epics:
        attention += _attention_for_row(r, "epic", ref)
    for r in work_items:
        attention += _attention_for_row(r, "work_item", ref)
    for r in pr_records:
        attention += _attention_for_row(r, "pr", ref)
    attention.sort(key=_rank_key)
    attention = attention[:ATTENTION_LIMIT]

    # --- KPI counts ---
    open_findings = sum(1 for r in findings if not _is_done(r.get("status")))
    active_epics = sum(1 for r in epics if not _is_done(r.get("status")))
    inflight_work = sum(1 for r in work_items if not _is_done(r.get("status")))
    open_prs = sum(1 for r in pr_records if not _is_done(r.get("state") or r.get("status")))

    # --- connector health roll-up ---
    connectors: list[dict[str, Any]] = []
    healthy = 0
    for c in list_connectors():
        try:
            h = await c.health()
        except Exception as e:  # noqa: BLE001 — health must never break the page
            h = {"status": "error", "detail": str(e)}
        try:
            s = await c.summary()
        except Exception:  # noqa: BLE001
            s = {}
        status = str(h.get("status", "unknown")).lower()
        if status in ("ok", "healthy", "up", "connected"):
            healthy += 1
        connectors.append(
            {
                "name": c.name,
                "status": status,
                "enabled": bool(getattr(c, "enabled", h.get("enabled", False))),
                "summary": _connector_line(s),
                "link": f"/hub?connector={c.name}",
            }
        )

    kpis = {
        "open_findings": open_findings,
        "active_epics": active_epics,
        "inflight_work_items": inflight_work,
        "open_prs": open_prs,
        "connectors_healthy": healthy,
        "connectors_total": len(connectors),
        "attention": len(attention),
    }

    tables = {
        "findings": findings[:TABLE_ROWS],
        "epics": epics[:TABLE_ROWS],
        "work_items": work_items[:TABLE_ROWS],
        "pr_records": pr_records[:TABLE_ROWS],
    }

    return {
        "kpis": kpis,
        "attention": attention,
        "connectors": connectors,
        "tables": tables,
        "generated_at": ref.isoformat(),
    }
