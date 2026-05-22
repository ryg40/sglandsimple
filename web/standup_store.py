"""Small JSON-backed store for Stage 20 standup websocket sessions.

The web container does not currently ship a Mongo driver, so this module keeps
standup session state in a local JSON file. It is intentionally narrow: enough
for refresh/reconnect persistence and websocket fanout, while all external
writes remain dry-run/placeholders.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

URL_RE = re.compile(r"https?://[^\s<>\]\)\"']+", re.IGNORECASE)
MENTION_RE = re.compile(r"(?<!\w)@([A-Za-z0-9._-]+)")
JIRA_KEY_RE = re.compile(r"(?<![A-Z0-9])([A-Z][A-Z0-9]+-\d+)(?![A-Z0-9])")
TRAILING_URL_PUNCT = ".,;:!?"
DEFAULT_MAX_MESSAGES = 500


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _default_store_path() -> Path:
    configured = os.environ.get("STANDUP_STORE_PATH", "").strip()
    if configured:
        return Path(configured)
    # The current compose file mounts /data/auth into the web container. Use it
    # when present so refreshes/restarts retain context without adding a new
    # compose volume in this slice; otherwise fall back to /tmp for local dev.
    data_auth = Path("/data/auth")
    if data_auth.is_dir():
        return data_auth / "standup_sessions.json"
    return Path(tempfile.gettempdir()) / "sglandsimple_standup_sessions.json"


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        clean = value.strip()
        if clean and clean not in seen:
            seen.add(clean)
            out.append(clean)
    return out


def _normalize_url(raw: str) -> str:
    return raw.rstrip(TRAILING_URL_PUNCT)


def _infer_service(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if "jira" in host or ("atlassian" in host and "/browse/" in path):
        return "jira"
    if "confluence" in host or ("atlassian" in host and "/wiki" in path):
        return "confluence"
    if "github" in host:
        return "github"
    if "servicenow" in host or ".service-now." in host or "snow" in host:
        return "servicenow"
    if "archer" in host:
        return "archer"
    if "snowflake" in host:
        return "snowflake"
    if "mongo" in host:
        return "mongodb"
    return "web"


def _jira_key_from_url(url: str) -> str | None:
    match = JIRA_KEY_RE.search(url.upper())
    return match.group(1) if match else None


def parse_links_mentions(body: str) -> dict[str, Any]:
    links: list[dict[str, Any]] = []
    for match in URL_RE.finditer(body):
        url = _normalize_url(match.group(0))
        links.append(
            {
                "url": url,
                "service": _infer_service(url),
                "label": urlparse(url).netloc or url,
                "jira_key": _jira_key_from_url(url),
            }
        )
    mentions = _dedupe([m.group(1) for m in MENTION_RE.finditer(body)])
    jira_keys = _dedupe([m.group(1) for m in JIRA_KEY_RE.finditer(body.upper())] + [link.get("jira_key") or "" for link in links])
    return {"links": links, "mentions": mentions, "jira_keys": jira_keys}


class StandupStore:
    """Tiny async facade around a JSON file for standup session state."""

    def __init__(self, path: Path | None = None, max_messages: int | None = None) -> None:
        self.path = path or _default_store_path()
        self.max_messages = max_messages or int(os.environ.get("STANDUP_MAX_MESSAGES", str(DEFAULT_MAX_MESSAGES)) or DEFAULT_MAX_MESSAGES)
        self._lock = asyncio.Lock()

    async def snapshot(self, session_id: str) -> dict[str, Any]:
        async with self._lock:
            data = self._load()
            session = self._ensure_session(data, session_id)
            self._save(data)
            return self._snapshot(session)

    async def touch_session(self, session_id: str, **updates: Any) -> dict[str, Any]:
        async with self._lock:
            data = self._load()
            session = self._ensure_session(data, session_id)
            allowed = {"title", "sprint", "epic_keys", "status", "created_by"}
            for key, value in updates.items():
                if key not in allowed or value in (None, ""):
                    continue
                if key == "epic_keys" and not isinstance(value, list):
                    value = [str(value)]
                session["session"][key] = value
            session["session"]["updated_at"] = utc_now()
            self._save(data)
            return self._snapshot(session)

    async def add_message(self, session_id: str, *, author: str, body: str, kind: str = "chat") -> dict[str, Any]:
        body = body.strip()
        if not body:
            raise ValueError("message body is required")
        async with self._lock:
            data = self._load()
            session = self._ensure_session(data, session_id)
            parsed = parse_links_mentions(body)
            message = {
                "id": uuid.uuid4().hex,
                "session_id": session_id,
                "author": author or "anonymous",
                "body": body,
                "kind": kind or "chat",
                "links": parsed["links"],
                "mentions": parsed["mentions"],
                "jira_keys": parsed["jira_keys"],
                "created_at": utc_now(),
            }
            session["messages"].append(message)
            if len(session["messages"]) > self.max_messages:
                session["messages"] = session["messages"][-self.max_messages :]
            session["session"]["updated_at"] = message["created_at"]
            self._save(data)
            return deepcopy(message)

    async def create_summary_placeholder(self, session_id: str, *, actor: str) -> dict[str, Any]:
        async with self._lock:
            data = self._load()
            session = self._ensure_session(data, session_id)
            recent_messages = session["messages"][-20:]
            now = utc_now()
            proposal = {
                "id": uuid.uuid4().hex,
                "session_id": session_id,
                "type": "meeting_followup",
                "target_service": "standup",
                "title": "Agent summary requested",
                "rationale": "Placeholder only: no LLM call, Jira staging, or external write was performed by the websocket handler.",
                "dry_run_payload": {
                    "summary": "Agent summarization placeholder pending MCP standup_summarize integration.",
                    "message_count": len(session["messages"]),
                    "recent_links": [link for msg in recent_messages for link in msg.get("links", [])],
                },
                "status": "proposed",
                "dry_run": True,
                "source_message_ids": [msg["id"] for msg in recent_messages],
                "created_by": actor or "anonymous",
                "created_at": now,
                "updated_at": now,
                "approval": None,
            }
            session["proposals"].append(proposal)
            session["session"]["updated_at"] = now
            self._save(data)
            return deepcopy(proposal)

    async def update_proposal_status(self, session_id: str, proposal_id: str, *, status: str, actor: str) -> dict[str, Any]:
        if status not in {"approved", "rejected"}:
            raise ValueError("status must be approved or rejected")
        async with self._lock:
            data = self._load()
            session = self._ensure_session(data, session_id)
            for proposal in session["proposals"]:
                if proposal.get("id") == proposal_id:
                    now = utc_now()
                    proposal["status"] = status
                    proposal["updated_at"] = now
                    proposal["approval"] = {
                        "actor": actor or "anonymous",
                        "decision": status,
                        "decided_at": now,
                        "dry_run_only": True,
                        "applied": False,
                    }
                    session["session"]["updated_at"] = now
                    self._save(data)
                    return deepcopy(proposal)
            raise KeyError(f"proposal not found: {proposal_id}")

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"sessions": {}}
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (json.JSONDecodeError, OSError):
            return {"sessions": {}}
        if not isinstance(data, dict):
            return {"sessions": {}}
        sessions = data.setdefault("sessions", {})
        if not isinstance(sessions, dict):
            data["sessions"] = {}
        return data

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
        os.replace(tmp, self.path)

    def _ensure_session(self, data: dict[str, Any], session_id: str) -> dict[str, Any]:
        clean_id = session_id.strip()
        if not clean_id:
            raise ValueError("session_id is required")
        sessions = data.setdefault("sessions", {})
        if clean_id not in sessions:
            now = utc_now()
            sessions[clean_id] = {
                "session": {
                    "session_id": clean_id,
                    "title": f"Standup {clean_id}",
                    "sprint": "",
                    "epic_keys": [],
                    "status": "active",
                    "created_by": "unknown",
                    "started_at": now,
                    "updated_at": now,
                    "ended_at": None,
                },
                "messages": [],
                "proposals": [],
                "agent_runs": [],
            }
        return sessions[clean_id]

    def _snapshot(self, session: dict[str, Any]) -> dict[str, Any]:
        return {
            "session": deepcopy(session.get("session", {})),
            "messages": deepcopy(session.get("messages", [])),
            "proposals": deepcopy(session.get("proposals", [])),
            "agent_runs": deepcopy(session.get("agent_runs", [])),
            "store": {"backend": "json_file", "path": str(self.path)},
        }


_STORE: StandupStore | None = None


def get_store() -> StandupStore:
    global _STORE
    if _STORE is None:
        _STORE = StandupStore()
    return _STORE
