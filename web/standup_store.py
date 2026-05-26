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


def _proposal_validation_state(raw: dict[str, Any], staging: dict[str, Any] | None) -> dict[str, Any]:
    if staging:
        state = str(staging.get("state") or "staged")
        return {"state": state, "details": deepcopy(staging)}
    proposal_type = str(raw.get("type") or "")
    target = str(raw.get("target_service") or "")
    if proposal_type == "new_jira_work" or target == "jira":
        return {
            "state": "not_staged",
            "reason": "retained as a dry-run standup proposal until HITL approval/apply is available",
        }
    return {"state": "not_required", "reason": "proposal does not require Stage-16 Jira validation"}


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

    async def add_message(self, session_id: str, *, author: str, body: str, kind: str = "chat", author_email: str = "", client_message_id: str = "") -> dict[str, Any]:
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
                "author_email": author_email or "",
                "body": body,
                "kind": kind or "chat",
                "client_message_id": client_message_id or "",
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

    async def persist_agent_result(
        self,
        session_id: str,
        *,
        actor: str,
        trigger: str,
        agent_result: dict[str, Any],
        staging_results: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist one standup agent run and its dry-run proposals."""
        async with self._lock:
            data = self._load()
            session = self._ensure_session(data, session_id)
            now = utc_now()
            run_id = f"standup-run-{uuid.uuid4().hex[:12]}"
            staging_results = staging_results or {}
            proposals: list[dict[str, Any]] = []
            for idx, raw in enumerate(agent_result.get("proposals") or [], start=1):
                if not isinstance(raw, dict):
                    continue
                proposal_id = str(raw.get("id") or f"standup-prop-{uuid.uuid4().hex[:12]}")
                dry_run_payload = raw.get("dry_run_payload") if isinstance(raw.get("dry_run_payload"), dict) else {}
                dry_run_payload.setdefault("dry_run", True)
                dry_run_payload.setdefault("agent_run_id", run_id)
                proposals.append(
                    {
                        "id": proposal_id,
                        "session_id": session_id,
                        "agent_run_id": run_id,
                        "type": str(raw.get("type") or "meeting_followup"),
                        "target_service": str(raw.get("target_service") or "standup"),
                        "title": str(raw.get("title") or raw.get("type") or f"Proposal {idx}"),
                        "rationale": str(raw.get("rationale") or ""),
                        "dry_run_payload": dry_run_payload,
                        "validation_state": _proposal_validation_state(raw, staging_results.get(proposal_id)),
                        "status": "proposed",
                        "dry_run": True,
                        "source_message_ids": list(raw.get("source_message_ids") or []),
                        "confidence": raw.get("confidence"),
                        "created_by": actor or "anonymous",
                        "created_at": now,
                        "updated_at": now,
                        "approval": None,
                    }
                )

            run = {
                "id": run_id,
                "session_id": session_id,
                "trigger": trigger or "manual",
                "summary": agent_result.get("summary") or "",
                "decisions": agent_result.get("decisions") or [],
                "risks_blockers": agent_result.get("risks_blockers") or [],
                "follow_ups": agent_result.get("follow_ups") or [],
                "service_associations": agent_result.get("service_associations") or [],
                "proposal_ids": [proposal["id"] for proposal in proposals],
                "proposal_count": len(proposals),
                "model": agent_result.get("model"),
                "dry_run_only": True,
                "created_by": actor or "anonymous",
                "created_at": now,
                "staging_results": staging_results,
            }
            session["agent_runs"].append(run)
            session["proposals"].extend(proposals)
            session["session"]["updated_at"] = now
            self._save(data)
            return {"agent_run": deepcopy(run), "proposals": deepcopy(proposals)}

    async def create_summary_placeholder(self, session_id: str, *, actor: str, error: str | None = None) -> dict[str, Any]:
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
                "rationale": "Fallback placeholder only: no Jira staging or external write was performed by the websocket handler.",
                "dry_run_payload": {
                    "summary": "Agent summarization unavailable; captured request as a dry-run proposal.",
                    "message_count": len(session["messages"]),
                    "recent_links": [link for msg in recent_messages for link in msg.get("links", [])],
                    "error": error,
                    "dry_run": True,
                },
                "validation_state": {"state": "not_staged", "reason": "agent summary unavailable; placeholder only"},
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

    async def update_proposal_status(
        self,
        session_id: str,
        proposal_id: str,
        *,
        status: str,
        actor: str,
        apply_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
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
                    approval = {
                        "actor": actor or "anonymous",
                        "decision": status,
                        "decided_at": now,
                        "dry_run_only": bool((apply_result or {}).get("dry_run_only", True)),
                        "applied": bool((apply_result or {}).get("applied", False)),
                    }
                    if apply_result is not None:
                        approval["apply_result"] = deepcopy(apply_result)
                    proposal["approval"] = approval
                    session["session"]["updated_at"] = now
                    self._save(data)
                    return deepcopy(proposal)
            raise KeyError(f"proposal not found: {proposal_id}")

    async def edit_proposal_payload(
        self, session_id: str, proposal_id: str, *, patch: dict[str, Any], actor: str
    ) -> dict[str, Any]:
        """Shallow-merge a patch into a still-proposed proposal's dry_run_payload.

        Only proposals in the ``proposed`` state may be edited; approved/rejected
        proposals are immutable. The ``dry_run`` marker is always preserved.
        """
        async with self._lock:
            data = self._load()
            session = self._ensure_session(data, session_id)
            for proposal in session["proposals"]:
                if proposal.get("id") == proposal_id:
                    if proposal.get("status") != "proposed":
                        raise ValueError("only proposed (not yet approved/rejected) proposals can be edited")
                    now = utc_now()
                    payload = proposal.get("dry_run_payload")
                    if not isinstance(payload, dict):
                        payload = {}
                    payload.update(patch)
                    payload["dry_run"] = True
                    proposal["dry_run_payload"] = payload
                    proposal["updated_at"] = now
                    proposal["edited_by"] = actor or "anonymous"
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
