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

    # GRC queue modeled on the real ServiceNow tables: `incident` and
    # `change_request`, using canonical field names. Rows now carry the same
    # finding/epic/ticket join keys as the other mock systems. The P1 incident
    # and the high-risk/high-impact change remain topology weak-spots.
    _SAMPLE = [
        {"record_type": "incident", "number": "INC0048213", "sys_id": "9c1f0a2b48213",
         "short_description": "RDS PostgreSQL prod audit pipeline not shipping logs",
         "description": "pgaudit events stopped flowing to S3 sink; SOX-404 evidence gap on prod DB.",
         "impact": "1 - High", "urgency": "1 - High", "priority": "1 - Critical", "state": "In Progress",
         "assignment_group": "Database Reliability", "assigned_to": "Sultan DevOps",
         "cmdb_ci": "rds-postgres-prod-02", "control": "SOX-404-SEC3",
         "finding_id": "finding-smoke-001", "epic_key": "RDS-LOG-1", "ticket_refs": ["RDS-LOG-3"],
         "opened_at": "2026-05-21 06:14", "sla_due": "2026-05-21 10:14", "sla_breach": True},
        {"record_type": "incident", "number": "INC0048190", "sys_id": "a72d5e9c48190",
         "short_description": "CloudTrail digest delivery delayed in eu-west-1",
         "description": "Digest files arriving >2h late; integrity verification window at risk.",
         "impact": "2 - Medium", "urgency": "2 - Medium", "priority": "3 - Moderate", "state": "On Hold",
         "assignment_group": "Cloud Platform", "assigned_to": "Sarah SRE",
         "cmdb_ci": "compliance-org-trail", "control": "PCI-DSS-10.5",
         "finding_id": "finding-smoke-001", "epic_key": "RDS-LOG-1", "ticket_refs": ["RDS-LOG-1"],
         "opened_at": "2026-05-20 13:02", "sla_due": "2026-05-22 13:02", "sla_breach": False},
        {"record_type": "incident", "number": "INC0048155", "sys_id": "b03c7f1148155",
         "short_description": "Confluence runbook link rot on SOX-404 page",
         "description": "Evidence index links 404; low impact, doc hygiene.",
         "impact": "3 - Low", "urgency": "3 - Low", "priority": "5 - Planning", "state": "New",
         "assignment_group": "Compliance Ops", "assigned_to": "Alex SecOps",
         "cmdb_ci": "Compliance-Runbooks", "control": "SOX-404-DOC",
         "finding_id": "finding-smoke-001", "epic_key": "RDS-LOG-1", "ticket_refs": ["RDS-LOG-2"],
         "opened_at": "2026-05-19 09:41", "sla_due": "2026-05-26 09:41", "sla_breach": False},
        {"record_type": "incident", "number": "INC0048231", "sys_id": "e88f6dc148231",
         "short_description": "Protected branch policy drift in sec-gates repository",
         "description": "Required status checks were removed from the main branch policy; PCI branch-control evidence is stale.",
         "impact": "2 - Medium", "urgency": "1 - High", "priority": "2 - High", "state": "In Progress",
         "assignment_group": "Security Engineering", "assigned_to": "Alex SecOps",
         "cmdb_ci": "sec-gates", "control": "PCI-DSS-v4-6.3",
         "finding_id": "finding-compliance-jira-01", "epic_key": "SEC-SCAN", "ticket_refs": ["SEC-SCAN-101", "SEC-SCAN-104"],
         "opened_at": "2026-05-22 08:12", "sla_due": "2026-05-23 08:12", "sla_breach": False},
        {"record_type": "change", "number": "CHG0012004", "sys_id": "c41a8b2212004",
         "short_description": "Cut over RDS MySQL prod to audit-enabled parameter group",
         "type": "normal", "risk": "High", "impact": "1 - High", "state": "Scheduled",
         "cab_required": True, "assignment_group": "Database Reliability",
         "cmdb_ci": "rds-mysql-prod-01", "control": "SOX-404-SEC3",
         "finding_id": "finding-smoke-001", "epic_key": "RDS-LOG-1", "ticket_refs": ["RDS-LOG-2", "RDS-LOG-3", "RDS-LOG-4"],
         "start_date": "2026-05-24 02:00", "end_date": "2026-05-24 04:00"},
        {"record_type": "change", "number": "CHG0012011", "sys_id": "d59e3c7712011",
         "short_description": "Rotate ALB TLS certificate (edge)",
         "type": "standard", "risk": "Moderate", "impact": "3 - Low", "state": "Scheduled",
         "cab_required": False, "assignment_group": "Cloud Platform",
         "cmdb_ci": "alb-compliance-edge", "control": "PCI-DSS-4.1",
         "finding_id": "finding-stale-certs-02", "epic_key": "ALB-ROT", "ticket_refs": ["ALB-ROT-202", "OPS-CERT-202"],
         "start_date": "2026-05-26 23:00", "end_date": "2026-05-26 23:30"},
        {"record_type": "change", "number": "CHG0012022", "sys_id": "f61aa7ea12022",
         "short_description": "Enable org-wide push protection on infrastructure repos",
         "type": "normal", "risk": "High", "impact": "2 - Medium", "state": "Assess",
         "cab_required": True, "assignment_group": "Security Engineering",
         "cmdb_ci": "sec-gates", "control": "PCI-DSS-v4-6.3",
         "finding_id": "finding-compliance-jira-01", "epic_key": "SEC-SCAN", "ticket_refs": ["SEC-SCAN-104"],
         "start_date": "2026-05-25 18:00", "end_date": "2026-05-25 19:00"},
    ]

    def _summary_payload(self, status: str) -> dict:
        return {
            "status": status,
            "schema": "snow_grc",
            "open_incidents": sum(1 for r in self._SAMPLE if r["record_type"] == "incident"),
            "p1_incidents": sum(1 for r in self._SAMPLE if str(r.get("priority", "")).startswith("1")),
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
