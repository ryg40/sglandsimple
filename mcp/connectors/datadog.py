"""Datadog (observability) connector — read-only mock.

Stage 21 (S21.extend.1) reference implementation that proves the *config-only
"add an agent"* path: a brand-new environment is brought online by adding this
connector class + one registry line + one `profiles.yaml` row, with **no change
to the orchestrator, the runtime, or `_dispatch_tool`** (connector tools are
auto-routed to `dispatch` in `server.py`). Mirrors the read-only AWS/ServiceNow
connector shape. Mock data only — no live Datadog API.
"""

from __future__ import annotations

import json
import os
from typing import Any


class DatadogConnector:
    """Read-only observability connector exposing monitors + recent events."""

    name = "datadog"

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled
        self.mcp_url = os.environ.get("DATADOG_MCP_URL", "")
        self.mcp_token = os.environ.get("DATADOG_MCP_TOKEN", "")

    async def health(self) -> dict:
        if not self.enabled:
            return {"status": "disabled"}
        if not self.mcp_url:
            return {"status": "degraded", "error": "Missing DATADOG_MCP_URL"}
        return {"status": "healthy", "url": self.mcp_url}

    # Mock monitors keyed to the same teaching dataset (finding/epic refs) so the
    # observability view reads like the rest of the stack.
    _MONITORS = [
        {"id": "mon-rds-audit-01", "name": "RDS audit logging disabled", "status": "Alert",
         "type": "metric alert", "env": "prod", "service": "rds-postgres-prod-02",
         "finding_id": "finding-smoke-001", "epic_key": "RDS-LOG-1"},
        {"id": "mon-alb-cert-02", "name": "ALB cert expiry < 30d", "status": "Warn",
         "type": "metric alert", "env": "prod", "service": "alb-compliance-edge",
         "finding_id": "finding-stale-certs-02", "epic_key": "ALB-ROT"},
        {"id": "mon-api-latency-03", "name": "payments-api p99 latency", "status": "OK",
         "type": "metric alert", "env": "prod", "service": "payments-api",
         "finding_id": None, "epic_key": None},
    ]

    _EVENTS = [
        {"id": "evt-9001", "title": "Deploy: payments-api v2.4.1", "tags": ["env:prod", "team:payments"],
         "alert_type": "info"},
        {"id": "evt-9002", "title": "Monitor triggered: RDS audit logging disabled",
         "tags": ["env:prod", "service:rds-postgres-prod-02"], "alert_type": "error"},
    ]

    async def summary(self) -> dict:
        base = {
            "schema": "datadog_observability",
            "monitors_count": len(self._MONITORS),
            "alerting_count": sum(1 for m in self._MONITORS if m["status"] in ("Alert", "Warn")),
            "events_count": len(self._EVENTS),
            "sample_data": self._MONITORS,
        }
        if not self.enabled:
            return {"status": "disabled", **base}
        return {"status": "healthy", **base}

    def tools(self) -> list[dict]:
        return [
            {
                "name": "datadog_list_monitors",
                "description": "List Datadog monitors with their current status (read-only).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "description": "Optional filter: Alert/Warn/OK."},
                    },
                },
            },
            {
                "name": "datadog_recent_events",
                "description": "List recent Datadog events (deploys, monitor triggers) (read-only).",
                "inputSchema": {"type": "object", "properties": {}},
            },
        ]

    async def dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            return {
                "content": [{"type": "text",
                             "text": f"Datadog connector is disabled. Tool '{name}' returned no data."}],
                "isError": False,
            }

        if name == "datadog_list_monitors":
            want = (args.get("status") or "").strip()
            rows = [m for m in self._MONITORS if not want or m["status"].lower() == want.lower()]
            return {"content": [{"type": "text", "text": json.dumps({"monitors": rows}, default=str)}],
                    "isError": False}
        if name == "datadog_recent_events":
            return {"content": [{"type": "text", "text": json.dumps({"events": self._EVENTS}, default=str)}],
                    "isError": False}

        return {"content": [{"type": "text", "text": f"Unknown tool: {name}"}], "isError": True}
