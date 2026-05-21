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

    # Auto-surfaced related content, modeled on the real Confluence content
    # shape (space/version/_links/ancestors/labels). `matched_on` expresses the
    # CQL-style relatedness: *why* each page surfaced — shared ticket numbers,
    # users, projects/spaces, or keywords.
    @staticmethod
    def _page(b, cid, title, space_key, space_name, ver, when, by, parent_id,
              labels, relevance, matched_on):
        return {
            "id": cid, "type": "page", "title": title,
            "space": {"key": space_key, "name": space_name},
            "version": {"number": ver, "when": when, "by": {"displayName": by}},
            "_links": {"webui": f"{b}/spaces/{space_key}/pages/{cid}"},
            "ancestors": ([{"id": parent_id}] if parent_id else []),
            "labels": labels,
            "relevance": relevance,
            "matched_on": matched_on,
            # convenience keys for simple rendering
            "url": f"{b}/spaces/{space_key}/pages/{cid}",
            "last_updated": when, "editor": by,
        }

    def _sample(self) -> list[dict]:
        b = self.base_url.rstrip("/")
        return [
            self._page(b, "100401", "Runbook: SOX-404 Database Audit Logging Procedure", "COMP",
                       "Compliance-Runbooks", 7, "2026-05-18", "Sultan DevOps", "100400",
                       ["sox-404", "runbook"], 0.94,
                       {"keywords": ["audit logging", "RDS"], "ticket_refs": ["RDS-LOG-1"],
                        "users": ["Sultan DevOps"], "projects": ["infra-terraform"]}),
            self._page(b, "100412", "CI/CD Secure Branch Scanning Policy & Compliance Standards", "ARCH",
                       "Architecture-RFCs", 3, "2026-05-20", "Alex SecOps", None,
                       ["security", "policy"], 0.88,
                       {"keywords": ["branch protection", "secret scanning"], "ticket_refs": ["SEC-SCAN-101"],
                        "users": ["Alex SecOps"], "projects": ["sec-gates"]}),
            self._page(b, "100420", "AWS Certificate Rotation Playbook (ALB Pipeline)", "SRE",
                       "SRE-Guides", 5, "2026-05-21", "Sarah SRE", None,
                       ["tls", "playbook"], 0.81,
                       {"keywords": ["certificate", "rotation", "ALB"], "ticket_refs": ["ALB-ROT-202"],
                        "users": ["Sarah SRE"], "projects": ["infra-k8s"]}),
            self._page(b, "100433", "Epic Log: RDS Audit Logging — Evidence Index", "COMP",
                       "Compliance-Runbooks", 11, "2026-05-21", "Sultan DevOps", "100400",
                       ["epic-log", "evidence"], 0.97,
                       {"keywords": ["evidence", "PCI-DSS-10.2"], "ticket_refs": ["RDS-LOG-1", "RDS-LOG-2"],
                        "users": ["Sultan DevOps"], "projects": ["infra-terraform"]}),
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
