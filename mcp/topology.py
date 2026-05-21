"""Stage 12 — cross-system interconnectivity topology.

Builds a `{nodes, edges, concerns}` graph for the Architecture page from the
connector registry. Nodes are the registered connectors (status/endpoint from
each connector's `health()`, headline metrics from `summary()`); edges encode
the compliance workflow relationships; concerns are computed weak-spots
(neglected Jira tickets, failing GitHub checks, prod RDS with audit logging
disabled, ServiceNow P1 incidents, high-risk upcoming changes).

No live calls — everything reads the connectors' mock/health surfaces.
"""

from __future__ import annotations

import os
from typing import Any

from connectors import get_connector, list_connectors

# Visual zones (left → right), AWS-architecture style. Each connector is placed
# in a zone so the web layout can arrange columns deterministically.
ZONES: dict[str, dict[str, Any]] = {
    "sources": {"label": "Risk & Findings", "order": 0, "members": ["archer", "servicenow"]},
    "workflow": {"label": "Delivery Workflow", "order": 1, "members": ["jira", "github", "confluence"]},
    "cloud": {"label": "Cloud Estate", "order": 2, "members": ["aws"]},
    "evidence": {"label": "Evidence & Records", "order": 3, "members": ["mongodb", "snowflake"]},
}

# System "kind" → used by the web layer to pick an icon.
KIND: dict[str, str] = {
    "archer": "shield",
    "servicenow": "ticket",
    "jira": "kanban",
    "github": "git",
    "confluence": "book",
    "aws": "cloud",
    "mongodb": "database",
    "snowflake": "snowflake",
}

LABELS: dict[str, str] = {
    "archer": "Archer (RIMS)",
    "servicenow": "ServiceNow",
    "jira": "Jira",
    "github": "GitHub",
    "confluence": "Confluence",
    "aws": "AWS",
    "mongodb": "MongoDB",
    "snowflake": "Snowflake",
}

# The compliance workflow relationships, as directed edges.
EDGES: list[dict[str, str]] = [
    {"from": "archer", "to": "servicenow", "label": "raises finding", "kind": "finding"},
    {"from": "servicenow", "to": "jira", "label": "finding → epic/ticket", "kind": "finding"},
    {"from": "jira", "to": "github", "label": "ticket → branch/PR", "kind": "delivery"},
    {"from": "github", "to": "confluence", "label": "PR → epic-log doc", "kind": "delivery"},
    {"from": "jira", "to": "confluence", "label": "epic-log", "kind": "delivery"},
    {"from": "github", "to": "aws", "label": "deploys to", "kind": "delivery"},
    {"from": "aws", "to": "snowflake", "label": "ships audit logs", "kind": "evidence"},
    {"from": "aws", "to": "mongodb", "label": "log samples", "kind": "evidence"},
    {"from": "jira", "to": "mongodb", "label": "work items (SoR)", "kind": "evidence"},
    {"from": "servicenow", "to": "mongodb", "label": "findings (SoR)", "kind": "evidence"},
    {"from": "confluence", "to": "mongodb", "label": "doc records (SoR)", "kind": "evidence"},
]


def _zone_of(name: str) -> str:
    for zone, meta in ZONES.items():
        if name in meta["members"]:
            return zone
    return "evidence"


def _node_metrics(name: str, summary: dict[str, Any]) -> dict[str, Any]:
    """Pick a few headline metrics per connector for the node + tooltip."""
    keys = {
        "aws": ["resources_count", "rds_instances_count", "logging_gaps"],
        "jira": ["open_issues_count", "flagged_count"],
        "servicenow": ["open_incidents", "p1_incidents", "upcoming_changes"],
        "github": ["commits_count", "prs_count", "failing_checks"],
        "confluence": ["pages_count"],
        "snowflake": ["audit_log_rows_count", "denied_count"],
        "mongodb": ["collections_count"],
        "archer": ["findings_tracked", "open_findings"],
    }.get(name, [])
    return {k: summary[k] for k in keys if k in summary}


def _concerns_for(name: str, summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Connector-specific weak-spot rules. Each concern points at its node."""
    out: list[dict[str, Any]] = []
    rows = summary.get("sample_data", []) or []

    if name == "jira":
        for r in rows:
            if r.get("flagged"):
                out.append({
                    "id": f"jira:{r.get('key')}", "severity": "high", "kind": "neglected_ticket",
                    "title": f"Neglected ticket {r.get('key')} — no update in {r.get('age_days')}d",
                    "node_id": "jira", "link": "/hub#jira",
                })
    elif name == "github":
        for r in rows:
            if r.get("checks_state") == "failing":
                out.append({
                    "id": f"gh:{r.get('sha')}", "severity": "high", "kind": "failing_checks",
                    "title": f"Failing checks on {r.get('repo')}@{r.get('sha')}",
                    "node_id": "github", "link": "/hub#github",
                })
    elif name == "aws":
        for r in rows:
            if r.get("service") == "RDS" and r.get("env") == "prod" and r.get("audit_logging") == "disabled":
                out.append({
                    "id": f"aws:{r.get('resource_id')}", "severity": "critical", "kind": "logging_disabled",
                    "title": f"Prod RDS {r.get('resource_id')} has audit logging DISABLED",
                    "node_id": "aws", "edge": {"from": "aws", "to": "snowflake"}, "link": "/hub#aws",
                })
    elif name == "servicenow":
        for r in rows:
            if r.get("record_type") == "incident" and str(r.get("priority", "")).startswith("1"):
                out.append({
                    "id": f"snow:{r.get('number')}", "severity": "critical", "kind": "p1_incident",
                    "title": f"P1 incident {r.get('number')} — {r.get('short_description')}",
                    "node_id": "servicenow", "link": "/hub#servicenow",
                })
            if r.get("record_type") == "change" and str(r.get("risk", "")).lower() == "high":
                out.append({
                    "id": f"snow:{r.get('number')}", "severity": "high", "kind": "risky_change",
                    "title": f"High-risk change {r.get('number')} scheduled {r.get('start_date')}",
                    "node_id": "servicenow", "link": "/hub#servicenow",
                })
    return out


async def build_topology() -> dict[str, Any]:
    include_disabled = os.environ.get("TOPOLOGY_INCLUDE_DISABLED", "true").lower() == "true"

    nodes: list[dict[str, Any]] = []
    concerns: list[dict[str, Any]] = []
    present: set[str] = set()

    for conn in list_connectors():
        name = conn.name
        try:
            health = await conn.health()
        except Exception as exc:  # noqa: BLE001
            health = {"status": "error", "detail": str(exc)}
        try:
            summary = await conn.summary()
        except Exception:  # noqa: BLE001
            summary = {}

        status = health.get("status", "unknown")
        if status == "disabled" and not include_disabled:
            continue

        node_concerns = _concerns_for(name, summary)
        concerns.extend(node_concerns)
        present.add(name)
        nodes.append({
            "id": name,
            "label": LABELS.get(name, name),
            "kind": KIND.get(name, "database"),
            "zone": _zone_of(name),
            "status": status,
            "endpoint": health.get("url") or summary.get("base_url") or "mcp::stub_loopback",
            "metrics": _node_metrics(name, summary),
            "concerns": [c["id"] for c in node_concerns],
        })

    # Mark edges that carry a concern (e.g. AWS→Snowflake logging gap).
    concern_edges = {(c["edge"]["from"], c["edge"]["to"]) for c in concerns if c.get("edge")}
    edges = [
        {**e, "concern": (e["from"], e["to"]) in concern_edges}
        for e in EDGES
        if e["from"] in present and e["to"] in present
    ]

    # Stable severity ordering for the concern list.
    rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    concerns.sort(key=lambda c: rank.get(c.get("severity", "low"), 9))

    zones = [{"id": z, **{k: v for k, v in meta.items() if k != "members"}}
             for z, meta in ZONES.items()]

    return {"nodes": nodes, "edges": edges, "concerns": concerns, "zones": zones}
