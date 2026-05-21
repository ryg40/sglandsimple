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
    # Archer (RIMS) API is provisioned.
    _SAMPLE = [
        {"finding_id": "arch-f-1", "control": "SOX-404-SEC3", "title": "Database audit logging not enforced on prod RDS",
         "severity": "high", "status": "open", "owner": "Sultan DevOps", "epic_key": "RDS-LOG-1"},
        {"finding_id": "arch-f-2", "control": "PCI-DSS-10.2", "title": "Log retention below required 365 days",
         "severity": "medium", "status": "open", "owner": "Sarah SRE", "epic_key": "RDS-LOG-1"},
        {"finding_id": "arch-f-3", "control": "SOX-404-SEC1", "title": "Branch protection gaps in infra repos",
         "severity": "medium", "status": "closed", "owner": "Alex SecOps", "epic_key": "SEC-SCAN"},
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
                        "text": '[{"finding_id":"arch-f-1","control":"SOX-404-SEC3","status":"open"},{"finding_id":"arch-f-2","control":"PCI-10.2","status":"closed"}]',
                    }
                ],
                "isError": False,
            }
        return {"content": [{"type": "text", "text": f"Unknown tool: {name}"}], "isError": True}
