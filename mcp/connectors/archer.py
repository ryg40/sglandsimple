"""Archer placeholder system connector client."""

from __future__ import annotations

from typing import Any

from .base import Connector


class ArcherConnector:
    """GRC Archer integration module (strictly static stub platform)."""

    name = "archer"

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled

    async def health(self) -> dict:
        # Archer is intentionally only supported in placeholder mode
        return {"status": "placeholder"}

    # Risk/audit findings feeding the workflow. Placeholder until a real
    # Archer (RIMS) API is provisioned. The finding ids now line up with the
    # Mongo findings collection and the downstream connector samples.
    _SAMPLE = [
        {"finding_id": "finding-smoke-001", "control": "SOX-404-SEC3", "title": "Database audit logging not enforced on prod RDS",
         "severity": "high", "status": "open", "owner": "Sultan DevOps", "epic_key": "RDS-LOG-1", "ticket_refs": ["RDS-LOG-1", "RDS-LOG-2", "RDS-LOG-3", "RDS-LOG-4"]},
        {"finding_id": "finding-compliance-jira-01", "control": "PCI-DSS-v4-6.3", "title": "Branch protection gaps in infrastructure repositories",
         "severity": "critical", "status": "open", "owner": "Alex SecOps", "epic_key": "SEC-SCAN", "ticket_refs": ["SEC-SCAN-101", "SEC-SCAN-104"]},
        {"finding_id": "finding-stale-certs-02", "control": "NIST-800-53-SC12", "title": "ALB TLS certificates lack verified automated rotation evidence",
         "severity": "high", "status": "open", "owner": "Sarah SRE", "epic_key": "ALB-ROT", "ticket_refs": ["ALB-ROT-202", "OPS-CERT-202"]},
        {"finding_id": "finding-unauth-access-03", "control": "SOC2-CC6.1", "title": "Stale IAM users retain production access beyond termination window",
         "severity": "medium", "status": "open", "owner": "Jordan IAM", "epic_key": "IAM-STALE-303", "ticket_refs": ["IAM-STALE-303"]},
    ]

    async def summary(self) -> dict:
        return {
            "status": "placeholder",
            "schema": "archer_findings",
            "findings_tracked": len(self._SAMPLE),
            "open_findings": sum(1 for r in self._SAMPLE if r["status"] == "open"),
            "sample_data": self._SAMPLE,
        }

    def tools(self) -> list[dict]:
        return [
            {
                "name": "archer_search_findings",
                "description": "Lookup compliance checklist findings inside the GRC register tool.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
        ]

    async def dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        # Always returns the mock payload directly (graceful grace registry)
        if name == "archer_search_findings":
            return {
                "content": [
                    {
                        "type": "text",
                        "text": '[{"finding_id":"finding-smoke-001","control":"SOX-404-SEC3","status":"open"},{"finding_id":"finding-compliance-jira-01","control":"PCI-DSS-v4-6.3","status":"open"},{"finding_id":"finding-stale-certs-02","control":"NIST-800-53-SC12","status":"open"}]',
                    }
                ],
                "isError": False,
            }
        return {"content": [{"type": "text", "text": f"Unknown tool: {name}"}], "isError": True}
