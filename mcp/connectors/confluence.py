"""Confluence connector client."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

import httpx

from .base import Connector

_SEARCH_TOOL_CANDIDATES = (
    "searchConfluenceUsingCql",
    "searchConfluence",
    "searchConfluencePages",
    "confluence_search_pages",
)
_CREATE_TOOL_CANDIDATES = (
    "createConfluencePage",
    "createPage",
    "confluence_create_page",
)
_UPDATE_TOOL_CANDIDATES = (
    "updateConfluencePage",
    "updateConfluencePageById",
    "updatePage",
    "confluence_update_page",
)
_ARG_ALIASES: dict[str, tuple[str, ...]] = {
    "query": ("query", "cql"),
    "title": ("title",),
    "space": ("space", "spaceKey", "space_key"),
    "body": ("body", "content"),
    "parent_id": ("parent_id", "parentId", "parentPageId", "ancestor_id"),
    "page_id": ("page_id", "pageId", "id"),
    "labels": ("labels", "labelNames"),
}


class ConfluenceConnector:
    """Connector for Confluence MCP server."""

    name = "confluence"

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled
        self.mcp_url = os.environ.get("CONFLUENCE_MCP_URL", "")
        self.mcp_token = os.environ.get("CONFLUENCE_TOKEN") or os.environ.get("CONFLUENCE_MCP_TOKEN", "")
        self.base_url = os.environ.get("CONFLUENCE_BASE_URL", "https://enterprise.atlassian.net/wiki")
        self._session_id: str | None = None
        self._rpc_id = 0

    async def health(self) -> dict:
        if not self.enabled:
            return {"status": "disabled"}
        if not self.mcp_url or not self.mcp_token:
            return {
                "status": "degraded",
                "error": "Missing CONFLUENCE_MCP_URL or CONFLUENCE_TOKEN (fallback CONFLUENCE_MCP_TOKEN)",
            }
        return {"status": "healthy", "url": self.mcp_url}

    # ---- live Atlassian MCP client ----------------------------------------

    @staticmethod
    def _parse_sse(text: str) -> dict[str, Any]:
        """The hosted server replies as text/event-stream; pull the JSON-RPC
        object out of the last `data:` line."""
        out: dict[str, Any] = {}
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                try:
                    out = json.loads(line[len("data:") :].strip())
                except json.JSONDecodeError:
                    continue
        return out

    async def _mcp_rpc(self, client: httpx.AsyncClient, method: str, params: dict | None = None) -> dict[str, Any]:
        self._rpc_id += 1
        headers = {
            "Authorization": f"Bearer {self.mcp_token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        body = {"jsonrpc": "2.0", "id": self._rpc_id, "method": method, "params": params or {}}
        r = await client.post(self.mcp_url, json=body, headers=headers)
        sid = r.headers.get("mcp-session-id")
        if sid:
            self._session_id = sid
        r.raise_for_status()
        return self._parse_sse(r.text)

    async def _live_tools(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        await self._mcp_rpc(
            client,
            "initialize",
            {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "langarland", "version": "0.1"}},
        )
        res = await self._mcp_rpc(client, "tools/list")
        return list((res.get("result", {}) or {}).get("tools", []) or [])

    @staticmethod
    def _flag(name: str) -> bool:
        return os.environ.get(name, "false").lower() == "true"

    def _has_live_creds(self) -> bool:
        return bool(self.enabled and self.mcp_url and self.mcp_token)

    def _live_writes_enabled(self) -> bool:
        return self._has_live_creds() and self._flag("WORKFLOW_WRITES_ENABLED") and self._flag("CONFLUENCE_WRITES_ENABLED")

    @staticmethod
    def _tool_schema_props(tool: dict[str, Any]) -> set[str]:
        schema = tool.get("inputSchema") or {}
        props = schema.get("properties") or {}
        return set(props)

    @classmethod
    def _shape_args(cls, tool: dict[str, Any], logical_args: dict[str, Any]) -> dict[str, Any]:
        accepted = cls._tool_schema_props(tool)
        shaped: dict[str, Any] = {}
        for logical_name, value in logical_args.items():
            if value is None or value == "" or value == []:
                continue
            aliases = _ARG_ALIASES.get(logical_name, (logical_name,))
            target = next((alias for alias in aliases if not accepted or alias in accepted), None)
            if target:
                shaped[target] = value
        return shaped

    @staticmethod
    def _pick_tool(candidates: tuple[str, ...], tools: list[dict[str, Any]]) -> dict[str, Any]:
        by_name = {t.get("name"): t for t in tools if t.get("name")}
        for candidate in candidates:
            if candidate in by_name:
                return by_name[candidate]
        names = [t.get("name") for t in tools if t.get("name")]
        raise RuntimeError(f"Atlassian MCP exposes no matching Confluence tool (saw: {names})")

    @staticmethod
    def _extract_json_block(payload: Any) -> dict[str, Any]:
        if isinstance(payload, dict):
            if isinstance(payload.get("structuredContent"), dict):
                return payload["structuredContent"]
            for block in reversed(payload.get("content", []) or []):
                if block.get("type") == "text":
                    try:
                        return json.loads(block["text"])
                    except (json.JSONDecodeError, KeyError, TypeError):
                        continue
            return payload
        return {}

    @classmethod
    def _deep_get(cls, payload: Any, *keys: str) -> Any:
        if isinstance(payload, dict):
            for key in keys:
                value = payload.get(key)
                if value not in (None, ""):
                    return value
            for value in payload.values():
                found = cls._deep_get(value, *keys)
                if found not in (None, ""):
                    return found
        elif isinstance(payload, list):
            for value in payload:
                found = cls._deep_get(value, *keys)
                if found not in (None, ""):
                    return found
        return None

    def _normalize_page_payload(self, payload: dict[str, Any], *, fallback_title: str | None = None, fallback_page_id: str | None = None) -> dict[str, Any]:
        data = self._extract_json_block(payload)
        page_id = self._deep_get(data, "pageId", "id") or fallback_page_id
        title = self._deep_get(data, "title", "name") or fallback_title
        url = self._deep_get(data, "url", "webui")
        if isinstance(url, str) and url.startswith("/"):
            url = self.base_url.rstrip("/") + url
        if not url and page_id:
            url = f"{self.base_url.rstrip('/')}/pages/{page_id}"
        out = {"status": "success"}
        if page_id:
            out["id"] = str(page_id)
        if title:
            out["title"] = title
        if url:
            out["url"] = url
        return out

    async def _call_live_tool(self, candidates: tuple[str, ...], logical_args: dict[str, Any]) -> dict[str, Any]:
        if not self._has_live_creds():
            raise RuntimeError("Confluence connector not configured for live Atlassian MCP access")
        async with httpx.AsyncClient(timeout=30) as client:
            tools = await self._live_tools(client)
            tool = self._pick_tool(candidates, tools)
            args = self._shape_args(tool, logical_args)
            return await self._mcp_rpc(client, "tools/call", {"name": tool["name"], "arguments": args})

    async def _live_search_pages(self, query: str) -> Any:
        escaped = query.replace('"', '\\"') if query else ""
        live = await self._call_live_tool(
            _SEARCH_TOOL_CANDIDATES,
            {"query": query, "cql": f'text ~ "{escaped}"' if query else ""},
        )
        result = live.get("result") or {}
        return self._extract_json_block(result)

    async def _live_create_page(self, args: dict[str, Any]) -> dict[str, Any]:
        live = await self._call_live_tool(
            _CREATE_TOOL_CANDIDATES,
            {
                "title": args.get("title"),
                "space": args.get("space"),
                "body": args.get("body"),
                "parent_id": args.get("parent_id"),
                "labels": args.get("labels"),
            },
        )
        return self._normalize_page_payload(live.get("result") or {}, fallback_title=args.get("title"))

    async def _live_update_page(self, args: dict[str, Any]) -> dict[str, Any]:
        live = await self._call_live_tool(
            _UPDATE_TOOL_CANDIDATES,
            {
                "page_id": args.get("page_id"),
                "title": args.get("title"),
                "body": args.get("body"),
                "labels": args.get("labels"),
            },
        )
        return self._normalize_page_payload(
            live.get("result") or {}, fallback_title=args.get("title"), fallback_page_id=args.get("page_id")
        )

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
        """Canonical Confluence sample rows.

        Keep this thin view aligned with `mongo-seed/15-confluence-pages.js` so
        connector summaries and Mongo-backed Ask Data/Wrangler queries describe
        the same overlap-chain world.
        """
        b = self.base_url.rstrip("/")
        return [
            self._page(
                b,
                "100401",
                "Runbook: SOX-404 Database Audit Logging Procedure",
                "COMP",
                "Compliance-Runbooks",
                7,
                "2026-05-18",
                "Sultan DevOps",
                "100400",
                ["sox-404", "runbook"],
                0.94,
                {
                    "finding_ids": ["finding-smoke-001"],
                    "epic_ids": ["epic-rds-001"],
                    "epic_keys": ["RDS-LOG-1"],
                    "work_item_ids": ["wi-rds-logging-01", "wi-rds-verify-06"],
                    "ticket_refs": ["RDS-LOG-1", "RDS-LOG-3"],
                    "keywords": ["audit logging", "RDS"],
                    "users": ["Sultan DevOps"],
                    "projects": ["infra-terraform"],
                },
            ),
            self._page(
                b,
                "100433",
                "Epic Log: RDS Audit Logging — Evidence Index",
                "COMP",
                "Compliance-Runbooks",
                11,
                "2026-05-21",
                "Sultan DevOps",
                "100400",
                ["epic-log", "evidence"],
                0.97,
                {
                    "finding_ids": ["finding-smoke-001"],
                    "epic_ids": ["epic-rds-001"],
                    "epic_keys": ["RDS-LOG-1"],
                    "work_item_ids": ["wi-rds-logging-01", "wi-rds-docs-05", "wi-rds-verify-06"],
                    "ticket_refs": ["RDS-LOG-1", "RDS-LOG-2", "RDS-LOG-3"],
                    "keywords": ["evidence", "PCI-DSS-10.2"],
                    "users": ["Sultan DevOps"],
                    "projects": ["infra-terraform"],
                },
            ),
            self._page(
                b,
                "100412",
                "CI/CD Secure Branch Scanning Policy & Compliance Standards",
                "ARCH",
                "Architecture-RFCs",
                3,
                "2026-05-20",
                "Alex SecOps",
                None,
                ["security", "policy"],
                0.88,
                {
                    "finding_ids": ["finding-compliance-jira-01"],
                    "epic_ids": ["epic-control-01"],
                    "epic_keys": ["SEC-SCAN-101"],
                    "work_item_ids": ["wi-scan-gate-02", "wi-scan-ruleset-07"],
                    "ticket_refs": ["SEC-SCAN-101", "SEC-SCAN-102"],
                    "keywords": ["branch protection", "secret scanning"],
                    "users": ["Alex SecOps"],
                    "projects": ["sec-gates"],
                },
            ),
            self._page(
                b,
                "100420",
                "AWS Certificate Rotation Playbook (ALB Pipeline)",
                "SRE",
                "SRE-Guides",
                5,
                "2026-05-21",
                "Sarah SRE",
                None,
                ["tls", "playbook"],
                0.81,
                {
                    "finding_ids": ["finding-stale-certs-02"],
                    "epic_ids": ["epic-certs-02"],
                    "epic_keys": ["OPS-CERT-202"],
                    "work_item_ids": ["wi-cert-rotate-03", "wi-cert-observability-08"],
                    "ticket_refs": ["OPS-CERT-202", "OPS-CERT-203"],
                    "keywords": ["certificate", "rotation", "ALB"],
                    "users": ["Sarah SRE"],
                    "projects": ["infra-k8s"],
                },
            ),
            self._page(
                b,
                "100455",
                "Stale IAM Exception Register & Owner Attestations",
                "SEC",
                "Security-Operations",
                4,
                "2026-05-22",
                "Priya Morgan",
                None,
                ["iam", "attestation"],
                0.86,
                {
                    "finding_ids": ["finding-unauth-access-03"],
                    "epic_ids": ["epic-access-03"],
                    "epic_keys": ["IAM-STALE-303"],
                    "work_item_ids": ["wi-iam-cleanup-04", "wi-iam-attestation-09"],
                    "ticket_refs": ["IAM-STALE-303", "IAM-STALE-304"],
                    "keywords": ["stale iam", "attestation"],
                    "users": ["Priya Morgan"],
                    "projects": ["identity-ops"],
                },
            ),
            self._page(
                b,
                "100460",
                "Evidence Warehouse Lineage Map",
                "DATA",
                "Data-Governance",
                2,
                "2026-05-23",
                "Umar Abdullah",
                None,
                ["lineage", "warehouse"],
                0.9,
                {
                    "finding_ids": ["finding-smoke-001"],
                    "epic_ids": ["epic-data-01"],
                    "epic_keys": ["DATA-EVID-404"],
                    "work_item_ids": ["wi-data-lineage-10"],
                    "ticket_refs": ["DATA-EVID-404"],
                    "keywords": ["warehouse", "lineage", "audit exports"],
                    "users": ["Umar Abdullah"],
                    "projects": ["evidence-warehouse"],
                },
            ),
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
        return self._summary_payload((await self.health()).get("status", "disabled"))

    @staticmethod
    def _mock_page_id(title: str, space: str, parent_id: str | None = None) -> str:
        seed = f"{space}\0{parent_id or ''}\0{title}".encode("utf-8")
        return "cp-" + hashlib.sha1(seed).hexdigest()[:12]

    def _mock_create_payload(self, args: dict[str, Any]) -> dict[str, Any]:
        title = args.get("title") or "page"
        space = args.get("space") or "SPACE"
        parent_id = args.get("parent_id")
        pid = self._mock_page_id(title, space, parent_id)
        return {
            "id": pid,
            "status": "success",
            "title": title,
            "url": f"{self.base_url.rstrip('/')}/pages/{pid}",
        }

    def _mock_update_payload(self, args: dict[str, Any]) -> dict[str, Any]:
        pid = str(args.get("page_id") or self._mock_page_id(args.get("title") or "page", "SPACE"))
        return {
            "id": pid,
            "status": "success",
            "title": args.get("title"),
            "url": f"{self.base_url.rstrip('/')}/pages/{pid}",
        }

    @staticmethod
    def _envelope(payload: Any, is_error: bool = False) -> dict[str, Any]:
        return {"content": [{"type": "text", "text": json.dumps(payload, default=str)}], "isError": is_error}

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
                        "parent_id": {"type": "string", "description": "Optional ancestor page id."},
                        "labels": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["title", "body"],
                },
            },
            {
                "name": "confluence_update_page",
                "description": "Update an existing Confluence page in place by id (Stage 14 sync idempotency).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "page_id": {"type": "string"},
                        "title": {"type": "string"},
                        "body": {"type": "string"},
                        "labels": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["page_id", "body"],
                },
            },
        ]

    async def dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        try:
            if name == "confluence_search_pages":
                if self._has_live_creds():
                    return self._envelope(await self._live_search_pages(args.get("query", "")))
                return self._envelope([])
            if name == "confluence_create_page":
                if self._live_writes_enabled():
                    return self._envelope(await self._live_create_page(args))
                return self._envelope(self._mock_create_payload(args))
            if name == "confluence_update_page":
                if self._live_writes_enabled():
                    return self._envelope(await self._live_update_page(args))
                return self._envelope(self._mock_update_payload(args))
        except Exception as e:  # noqa: BLE001
            return self._envelope({"error": f"{type(e).__name__}: {e}"}, is_error=True)

        return {"content": [{"type": "text", "text": f"Unknown tool: {name}"}], "isError": True}
