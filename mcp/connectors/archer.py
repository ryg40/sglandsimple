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

    async def summary(self) -> dict:
        return {"status": "placeholder", "findings_tracked": 2}

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
