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

    async def summary(self) -> dict:
        if not self.enabled:
            return {"status": "disabled"}
        return {"status": "healthy", "open_incidents": 5, "change_requests": 2}

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
