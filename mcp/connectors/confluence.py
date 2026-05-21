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

    async def health(self) -> dict:
        if not self.enabled:
            return {"status": "disabled"}
        return {"status": "healthy", "url": self.mcp_url}

    async def summary(self) -> dict:
        if not self.enabled:
            return {"status": "disabled", "pages_count": 0}
        return {"status": "healthy", "pages_count": 12}

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
