"""Confluence connector client."""

from __future__ import annotations

import os
from typing import Any

from .base import Connector


class ConfluenceConnector:
    """Connector for Confluence MCP server."""

    name = "confluence"

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled
        self.mcp_url = os.environ.get("CONFLUENCE_MCP_URL", "")
        self.mcp_token = os.environ.get("CONFLUENCE_MCP_TOKEN", "")
        self.base_url = os.environ.get("CONFLUENCE_BASE_URL", "https://enterprise.atlassian.net/wiki")

    async def health(self) -> dict:
        if not self.enabled:
            return {"status": "disabled"}
        if not self.mcp_url or not self.mcp_token:
            return {"status": "degraded", "error": "Missing CONFLUENCE_MCP_URL or CONFLUENCE_MCP_TOKEN"}
        return {"status": "healthy", "url": self.mcp_url}

    # Auto-surfaced related articles. `matched_on` explains *why* each page was
    # linked in: shared ticket numbers, users, projects, or keywords.
    def _sample(self) -> list[dict]:
        b = self.base_url.rstrip("/")
        return [
            {"id": "pg-01", "title": "Runbook: SOX-404 Database Audit Logging Procedure",
             "space": "Compliance-Runbooks", "last_updated": "2026-05-18", "relevance": 0.94,
             "url": f"{b}/spaces/COMP/pages/100401",
             "matched_on": {"keywords": ["audit logging", "RDS"], "ticket_refs": ["RDS-LOG-1"],
                            "users": ["Sultan DevOps"], "projects": ["infra-terraform"]}},
            {"id": "pg-02", "title": "CI/CD Secure Branch Scanning Policy & Compliance Standards",
             "space": "Architecture-RFCs", "last_updated": "2026-05-20", "relevance": 0.88,
             "url": f"{b}/spaces/ARCH/pages/100412",
             "matched_on": {"keywords": ["branch protection", "secret scanning"], "ticket_refs": ["SEC-SCAN-101"],
                            "users": ["Alex SecOps"], "projects": ["sec-gates"]}},
            {"id": "pg-03", "title": "AWS Certificate Rotation Playbook (ALB Pipeline)",
             "space": "SRE-Guides", "last_updated": "2026-05-21", "relevance": 0.81,
             "url": f"{b}/spaces/SRE/pages/100420",
             "matched_on": {"keywords": ["certificate", "rotation", "ALB"], "ticket_refs": ["ALB-ROT-202"],
                            "users": ["Sarah SRE"], "projects": ["infra-k8s"]}},
            {"id": "pg-04", "title": "Epic Log: RDS Audit Logging — Evidence Index",
             "space": "Compliance-Runbooks", "last_updated": "2026-05-21", "relevance": 0.97,
             "url": f"{b}/spaces/COMP/pages/100433",
             "matched_on": {"keywords": ["evidence", "PCI-DSS-10.2"], "ticket_refs": ["RDS-LOG-1", "RDS-LOG-2"],
                            "users": ["Sultan DevOps"], "projects": ["infra-terraform"]}},
        ]

    def _summary_payload(self, status: str) -> dict:
        sample = self._sample()
        return {
            "status": status,
            "schema": "confluence_links",
            "pages_count": len(sample),
            "base_url": self.base_url,
            "sample_data": sample,
        }

    async def summary(self) -> dict:
        return self._summary_payload("disabled" if not self.enabled else "healthy")

    def tools(self) -> list[dict]:
        return [
            {
                "name": "confluence_search_pages",
                "description": "Search Confluence pages.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"}
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "confluence_create_page",
                "description": "Create a Confluence page.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "space": {"type": "string"},
                        "body": {"type": "string"},
                    },
                    "required": ["title", "body"],
                },
            },
        ]

    async def dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            return {
                "content": [{"type": "text", "text": f"Confluence connector is disabled. Tool '{name}' returned generic stub payload."}],
                "isError": False,
            }

        if name == "confluence_search_pages":
            return {"content": [{"type": "text", "text": "[]"}], "isError": False}
        if name == "confluence_create_page":
            return {"content": [{"type": "text", "text": f'{{"url": "https://confluence.example.com/pages/{args.get("title", "page")}", "status": "success"}}'}], "isError": False}

        return {"content": [{"type": "text", "text": f"Unknown tool: {name}"}], "isError": True}
