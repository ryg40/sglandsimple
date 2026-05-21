"""ServiceNow connector client using direct REST or HTTP stubs."""

from __future__ import annotations

import os
from typing import Any

import httpx

from .base import Connector


class ServiceNowConnector:
    """Connector for ServiceNow GRC & Incident Management REST API."""

    name = "servicenow"

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled
        self.url = os.environ.get("SERVICENOW_URL", "https://example.service-now.com")
        self.token = os.environ.get("SERVICENOW_TOKEN", "")

    async def health(self) -> dict:
        if not self.enabled:
            return {"status": "disabled"}
        if not self.url or not self.token:
            return {"status": "degraded", "error": "Missing SERVICENOW_URL or SERVICENOW_TOKEN"}
        try:
            # Table API client sanity check as health-probe Table GET
            headers = {"Authorization": f"Bearer {self.token}"}
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(f"{self.url}/api/now/table/sys_user?sysparm_limit=1", headers=headers)
                if r.status_code == 200:
                    return {"status": "healthy"}
                return {"status": "degraded", "code": r.status_code}
        except Exception as e:  # noqa: BLE001
            return {"status": "error", "detail": str(e)}

    # GRC queue: high-priority open incidents + the upcoming change calendar.
    # The P1 incident and the high-risk/high-impact change are weak-spots the
    # topology highlights (potential outage / business impact).
    _SAMPLE = [
        {"record_type": "incident", "number": "INC0048213", "priority": "P1",
         "summary": "RDS PostgreSQL prod audit pipeline not shipping logs", "ci": "rds-postgres-prod-02",
         "opened": "2026-05-21", "state": "In Progress", "sla_breach": True},
        {"record_type": "incident", "number": "INC0048190", "priority": "P2",
         "summary": "CloudTrail digest delivery delayed in eu-west-1", "ci": "compliance-org-trail",
         "opened": "2026-05-20", "state": "On Hold", "sla_breach": False},
        {"record_type": "incident", "number": "INC0048155", "priority": "P3",
         "summary": "Confluence runbook link rot on SOX-404 page", "ci": "Compliance-Runbooks",
         "opened": "2026-05-19", "state": "New", "sla_breach": False},
        {"record_type": "change", "number": "CHG0012004", "summary": "Cut over RDS MySQL prod to audit-enabled parameter group",
         "ci": "rds-mysql-prod-01", "window_start": "2026-05-24 02:00", "window_end": "2026-05-24 04:00",
         "risk": "high", "impact": "high", "state": "Scheduled"},
        {"record_type": "change", "number": "CHG0012011", "summary": "Rotate ALB TLS certificate (edge)",
         "ci": "alb-compliance-edge", "window_start": "2026-05-26 23:00", "window_end": "2026-05-26 23:30",
         "risk": "medium", "impact": "low", "state": "Scheduled"},
    ]

    def _summary_payload(self, status: str) -> dict:
        return {
            "status": status,
            "schema": "snow_grc",
            "open_incidents": sum(1 for r in self._SAMPLE if r["record_type"] == "incident"),
            "p1_incidents": sum(1 for r in self._SAMPLE if r.get("priority") == "P1"),
            "upcoming_changes": sum(1 for r in self._SAMPLE if r["record_type"] == "change"),
            "sample_data": self._SAMPLE,
        }

    async def summary(self) -> dict:
        return self._summary_payload("disabled" if not self.enabled else "healthy")

    def tools(self) -> list[dict]:
        return [
            {
                "name": "servicenow_search_findings",
                "description": "Query open GRC findings/issues.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "severity": {"type": "string"},
                        "limit": {"type": "integer", "default": 10},
                    },
                },
            },
            {
                "name": "servicenow_get_change_request",
                "description": "Fetch status of a specific ServiceNow ticket / RFC change query.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "sys_id": {"type": "string"},
                    },
                    "required": ["sys_id"],
                },
            },
        ]

    async def dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            return {
                "content": [{"type": "text", "text": f"ServiceNow connector is disabled. Tool '{name}' returned generic stub payload."}],
                "isError": False,
            }

        if name == "servicenow_search_findings":
            return {"content": [{"type": "text", "text": '[{"sys_id":"fnd01","summary":"Database lacks audit control","severity":"high"}]'}], "isError": False}
        if name == "servicenow_get_change_request":
            return {"content": [{"type": "text", "text": '{"sys_id":"chg456","state":"approved","summary":"Deploy RDS Audit policy"}'}], "isError": False}

        return {"content": [{"type": "text", "text": f"Unknown tool: {name}"}], "isError": True}
