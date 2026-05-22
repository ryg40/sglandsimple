"""FastAPI routes for Stage 20 standup session snapshots and websocket fanout."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

import auth as _auth
from standup_store import get_store

router = APIRouter()

MCP_URL = os.environ.get("MCP_URL", "http://mcp:8080/mcp")
MCP_AUTH_TOKEN = os.environ.get("MCP_AUTH_TOKEN") or ""
REQUEST_TIMEOUT = float(os.environ.get("REQUEST_TIMEOUT", "300"))
_mcp_session_id: str | None = None
_mcp_rpc_id = 0


def _env_bool(key: str, default: bool = True) -> bool:
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _event_type(data: dict[str, Any]) -> str:
    return str(data.get("type") or data.get("event") or data.get("name") or "")


def _payload(data: dict[str, Any]) -> dict[str, Any]:
    payload = data.get("payload")
    return payload if isinstance(payload, dict) else data


def _next_rpc_id() -> int:
    global _mcp_rpc_id
    _mcp_rpc_id += 1
    return _mcp_rpc_id


def _mcp_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if MCP_AUTH_TOKEN:
        headers["Authorization"] = f"Bearer {MCP_AUTH_TOKEN}"
    if _mcp_session_id:
        headers["Mcp-Session-Id"] = _mcp_session_id
    return headers


async def _mcp_initialize(client: httpx.AsyncClient) -> None:
    global _mcp_session_id
    body = {
        "jsonrpc": "2.0",
        "id": _next_rpc_id(),
        "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
    }
    response = await client.post(MCP_URL, json=body, headers=_mcp_headers())
    response.raise_for_status()
    _mcp_session_id = response.headers.get("Mcp-Session-Id") or response.headers.get("mcp-session-id") or _mcp_session_id


async def _mcp_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    global _mcp_session_id
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        if _mcp_session_id is None:
            await _mcp_initialize(client)
        body = {"jsonrpc": "2.0", "id": _next_rpc_id(), "method": "tools/call", "params": {"name": name, "arguments": arguments}}
        response = await client.post(MCP_URL, json=body, headers=_mcp_headers())
        if response.status_code in (400, 404) and "session" in response.text.lower():
            _mcp_session_id = None
            await _mcp_initialize(client)
            response = await client.post(MCP_URL, json=body, headers=_mcp_headers())
        response.raise_for_status()
        data = response.json()
    if data.get("error"):
        raise RuntimeError(f"MCP error from {name}: {data['error']}")
    result = data.get("result") or {}
    if result.get("isError"):
        payload = _extract_json_block(result)
        raise RuntimeError(str(payload.get("error") or payload or f"MCP tool {name} failed"))
    return result


def _extract_json_block(result: dict[str, Any]) -> Any:
    blocks = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
    for text in reversed(blocks):
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            continue
    return {"raw": "\n".join(blocks)}


def _fallback_identity(websocket: WebSocket) -> tuple[str, str]:
    for header in ("x-forwarded-user", "x-user", "x-auth-request-user"):
        value = websocket.headers.get(header)
        if value:
            return value, value if "@" in value else ""
    author = websocket.query_params.get("author") or "anonymous"
    email = websocket.query_params.get("email") or ""
    return author, email


def _resolved_identity(websocket: WebSocket) -> tuple[str, str, bool, Any]:
    """Resolve S19 identity for a websocket, falling back to legacy hints.

    Starlette WebSocket exposes a request-like ``headers`` mapping, which is
    enough for auth.resolve_user() across basic/header/SSO/trusted modes.

    Returns ``(author, email, authenticated, user_context_or_None)``.
    """
    try:
        user = _auth.resolve_user(websocket)
    except Exception:
        user = None
    if user is not None and _auth.CONFIG.auth_mode != "disabled":
        return user.display_name or user.username or "anonymous", user.email or "", True, user
    author, email = _fallback_identity(websocket)
    return author, email, False, None


def _can_approve(state: "ClientState") -> bool:
    """Whether this client may approve/reject standup proposals.

    Approval requires the Stage-19 ``canApproveStandupActions`` capability,
    which currently maps to the admin role. When auth is disabled the resolver
    returns a full-capability admin context, so disabled mode also passes.
    Unauthenticated/legacy-fallback clients never gain approval rights.
    """
    user = state.user
    if user is None:
        return False
    try:
        return user.has(_auth.Capability.CAN_APPROVE_STANDUP)
    except Exception:
        return False


@dataclass
class ClientState:
    client_id: str
    session_id: str
    author: str
    email: str = ""
    authenticated: bool = False
    typing: bool = False
    user: Any = None  # resolved auth.UserContext when authenticated, else None


class StandupConnectionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, dict[WebSocket, ClientState]] = {}

    async def connect(self, websocket: WebSocket, session_id: str) -> ClientState:
        await websocket.accept()
        author, email, authenticated, user = _resolved_identity(websocket)
        state = ClientState(
            client_id=uuid.uuid4().hex,
            session_id=session_id,
            author=author,
            email=email,
            authenticated=authenticated,
            user=user,
        )
        self._sessions.setdefault(session_id, {})[websocket] = state
        return state

    def disconnect(self, websocket: WebSocket, session_id: str) -> ClientState | None:
        clients = self._sessions.get(session_id)
        if not clients:
            return None
        state = clients.pop(websocket, None)
        if not clients:
            self._sessions.pop(session_id, None)
        return state

    def participants(self, session_id: str) -> list[dict[str, Any]]:
        clients = self._sessions.get(session_id, {})
        return [
            {
                "client_id": state.client_id,
                "author": state.author,
                "display_name": state.author,
                "email": state.email,
                "typing": state.typing,
                "can_approve": _can_approve(state),
            }
            for state in clients.values()
        ]

    async def send(self, websocket: WebSocket, event: dict[str, Any]) -> None:
        await websocket.send_json(event)

    async def broadcast(self, session_id: str, event: dict[str, Any]) -> None:
        stale: list[WebSocket] = []
        for websocket in list(self._sessions.get(session_id, {})):
            try:
                await websocket.send_json(event)
            except Exception:
                stale.append(websocket)
        for websocket in stale:
            self.disconnect(websocket, session_id)

    async def broadcast_presence(self, session_id: str) -> None:
        await self.broadcast(
            session_id,
            {
                "type": "presence.update",
                "session_id": session_id,
                "presence": {"participants": self.participants(session_id)},
            },
        )


manager = StandupConnectionManager()


@router.get("/api/standup/sessions/{session_id}/snapshot")
async def standup_snapshot(session_id: str, request: Request) -> JSONResponse:
    # S20.auth.1 — viewing a session snapshot requires an authenticated identity
    # (any role). Approval gating happens separately over the websocket.
    _auth.require_user(request)
    snapshot = await get_store().snapshot(session_id)
    snapshot["presence"] = {"participants": manager.participants(session_id)}
    return JSONResponse(snapshot)


@router.websocket("/api/standup/ws/{session_id}")
async def standup_ws(websocket: WebSocket, session_id: str) -> None:
    if not _env_bool("STANDUP_WS_ENABLED", True):
        await websocket.close(code=1008, reason="standup websocket disabled")
        return

    state = await manager.connect(websocket, session_id)

    # S20.auth.1 — gate session join on a resolved Stage-19 identity. When auth
    # is disabled (local dev) resolve_user() returns a synthetic admin, so this
    # only rejects genuinely unauthenticated clients in basic/sso/header modes.
    if _auth.CONFIG.auth_mode != "disabled" and not state.authenticated:
        await manager.send(
            websocket,
            {
                "type": "error",
                "session_id": session_id,
                "error": {"code": "unauthenticated", "message": "Sign in to join the standup session."},
            },
        )
        manager.disconnect(websocket, session_id)
        await websocket.close(code=1008, reason="authentication required")
        return
    try:
        snapshot = await get_store().snapshot(session_id)
        snapshot["presence"] = {"participants": manager.participants(session_id)}
        await manager.send(websocket, {"type": "session.snapshot", "session_id": session_id, "snapshot": snapshot})
        await manager.broadcast_presence(session_id)

        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise ValueError("event must be a JSON object")
            except (json.JSONDecodeError, ValueError) as exc:
                await _send_error(websocket, session_id, "invalid_json", str(exc))
                continue

            event_type = _event_type(data)
            payload = _payload(data)
            try:
                if event_type == "join":
                    await _handle_join(websocket, session_id, state, payload)
                elif event_type == "chat.message":
                    await _handle_chat_message(session_id, state, payload)
                elif event_type == "typing":
                    await _handle_typing(session_id, state, payload)
                elif event_type == "agent.summarize":
                    await _handle_agent_summarize(session_id, state, payload)
                elif event_type == "proposal.edit":
                    await _handle_proposal_edit(websocket, session_id, state, payload)
                elif event_type == "proposal.approve":
                    await _handle_proposal_status(websocket, session_id, state, payload, "approved")
                elif event_type == "proposal.reject":
                    await _handle_proposal_status(websocket, session_id, state, payload, "rejected")
                else:
                    await _send_error(websocket, session_id, "unknown_event", f"unsupported event type: {event_type or '<missing>'}")
            except ValueError as exc:
                await _send_error(websocket, session_id, "bad_request", str(exc))
            except KeyError as exc:
                await _send_error(websocket, session_id, "not_found", str(exc))
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket, session_id)
        await manager.broadcast_presence(session_id)


async def _handle_join(websocket: WebSocket, session_id: str, state: ClientState, payload: dict[str, Any]) -> None:
    if not state.authenticated:
        author = str(payload.get("display_name") or payload.get("author") or payload.get("user") or state.author or "anonymous").strip() or "anonymous"
        email = str(payload.get("email") or state.email or "").strip()
        state.author = author
        state.email = email
    snapshot = await get_store().touch_session(
        session_id,
        title=payload.get("title"),
        sprint=payload.get("sprint"),
        epic_keys=payload.get("epic_keys"),
        created_by=state.author,
    )
    snapshot["presence"] = {"participants": manager.participants(session_id)}
    await manager.send(websocket, {"type": "session.snapshot", "session_id": session_id, "snapshot": snapshot})
    await manager.broadcast_presence(session_id)


async def _handle_chat_message(session_id: str, state: ClientState, payload: dict[str, Any]) -> None:
    body = str(payload.get("body") or payload.get("text") or payload.get("content") or "")
    kind = str(payload.get("kind") or "chat")
    message = await get_store().add_message(session_id, author=state.author, author_email=state.email, body=body, kind=kind)
    await manager.broadcast(session_id, {"type": "chat.message", "session_id": session_id, "message": message})


async def _handle_typing(session_id: str, state: ClientState, payload: dict[str, Any]) -> None:
    state.typing = bool(payload.get("typing", True))
    await manager.broadcast_presence(session_id)


async def _handle_agent_summarize(session_id: str, state: ClientState, payload: dict[str, Any]) -> None:
    await manager.broadcast(session_id, {"type": "agent.running", "session_id": session_id, "actor": state.author})
    snapshot = await get_store().snapshot(session_id)
    trigger = str(payload.get("trigger") or "manual")
    try:
        agent_result = await _run_standup_agent(snapshot, payload, trigger=trigger)
        if not agent_result.get("proposals"):
            agent_result["proposals"] = [_summary_followup_proposal(agent_result, snapshot)]
        staging_results = await _stage_jira_edit_proposals(agent_result.get("proposals") or [], state)
        persisted = await get_store().persist_agent_result(
            session_id,
            actor=state.author,
            trigger=trigger,
            agent_result=agent_result,
            staging_results=staging_results,
        )
    except Exception as exc:  # noqa: BLE001 - websocket should degrade to persisted dry-run capture
        proposal = await get_store().create_summary_placeholder(session_id, actor=state.author, error=f"{type(exc).__name__}: {exc}")
        await manager.broadcast(session_id, {"type": "proposal.updated", "session_id": session_id, "proposal": proposal})
        await manager.broadcast(
            session_id,
            {
                "type": "agent.summary",
                "session_id": session_id,
                "agent_run": None,
                "proposals": [proposal],
                "error": str(exc),
            },
        )
        return

    await manager.broadcast(
        session_id,
        {
            "type": "agent.summary",
            "session_id": session_id,
            "agent_run": persisted["agent_run"],
            "proposals": persisted["proposals"],
        },
    )
    for proposal in persisted["proposals"]:
        await manager.broadcast(session_id, {"type": "proposal.created", "session_id": session_id, "proposal": proposal})
        await manager.broadcast(session_id, {"type": "proposal.updated", "session_id": session_id, "proposal": proposal})


async def _run_standup_agent(snapshot: dict[str, Any], payload: dict[str, Any], *, trigger: str) -> dict[str, Any]:
    injected_result = payload.get("agent_result")
    if isinstance(injected_result, dict) and _env_bool("STANDUP_ALLOW_INJECTED_AGENT_RESULT", False):
        return injected_result
    result = await _mcp_tool(
        "standup_summarize",
        {
            "messages": snapshot.get("messages") or [],
            "selected_issues": payload.get("selected_issues") or [],
            "docs_context": payload.get("docs_context") or [],
            "trigger": trigger,
            "max_messages": int(payload.get("max_messages") or 80),
        },
    )
    agent_result = _extract_json_block(result)
    if not isinstance(agent_result, dict):
        raise RuntimeError("standup_summarize returned a non-object payload")
    return agent_result


def _summary_followup_proposal(agent_result: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    messages = snapshot.get("messages") or []
    recent = messages[-20:]
    return {
        "id": f"standup-prop-{uuid.uuid4().hex[:12]}",
        "type": "meeting_followup",
        "target_service": "standup",
        "title": "Standup summary captured",
        "rationale": "Agent returned a summary without concrete Jira create/edit proposals; retained as dry-run meeting context.",
        "dry_run_payload": {
            "summary": agent_result.get("summary") or "",
            "message_count": len(messages),
            "dry_run": True,
        },
        "source_message_ids": [msg.get("id") for msg in recent if msg.get("id")],
        "confidence": 0.5,
        "status": "proposed",
        "dry_run": True,
    }


def _jira_edits_from_proposal(proposal: dict[str, Any]) -> list[dict[str, Any]]:
    if str(proposal.get("target_service") or "") != "jira" or str(proposal.get("type") or "") != "jira_edit":
        return []
    payload = proposal.get("dry_run_payload") if isinstance(proposal.get("dry_run_payload"), dict) else {}
    edits = payload.get("edits")
    if isinstance(edits, list):
        return [edit for edit in edits if isinstance(edit, dict) and edit.get("issue_key") and isinstance(edit.get("changes"), dict)]
    issue_key = payload.get("issue_key") or payload.get("key")
    changes = payload.get("changes") or payload.get("fields")
    if issue_key and isinstance(changes, dict):
        return [{"issue_key": issue_key, "changes": changes}]
    issue_keys = payload.get("issue_keys") or payload.get("target_issue_keys")
    if isinstance(issue_keys, list) and isinstance(changes, dict):
        return [{"issue_key": key, "changes": changes} for key in issue_keys if key]
    return []


async def _stage_jira_edit_proposals(proposals: list[dict[str, Any]], state: ClientState) -> dict[str, Any]:
    staging_results: dict[str, Any] = {}
    actor = {"display_name": state.author, "email": state.email}
    for proposal in proposals:
        if not isinstance(proposal, dict):
            continue
        proposal_id = str(proposal.get("id") or "")
        edits = _jira_edits_from_proposal(proposal)
        if not proposal_id or not edits:
            continue
        try:
            stage_result = _extract_json_block(await _mcp_tool("jira_stage_edits", {"edits": edits, "actor": actor}))
            issue_keys = [str(edit.get("issue_key")) for edit in edits if edit.get("issue_key")]
            validation_result = _extract_json_block(
                await _mcp_tool("jira_validate_staged", {"issue_keys": issue_keys, "actor": actor})
            )
            validated = validation_result.get("validated", 0) if isinstance(validation_result, dict) else 0
            state_name = "validated" if validated == len(issue_keys) else "invalid"
            staging_results[proposal_id] = {
                "state": state_name,
                "stage16": {"stage": stage_result, "validation": validation_result},
                "issue_keys": issue_keys,
                "dry_run_only": True,
            }
        except Exception as exc:  # noqa: BLE001
            staging_results[proposal_id] = {
                "state": "staging_failed",
                "error": f"{type(exc).__name__}: {exc}",
                "edits": edits,
                "dry_run_only": True,
            }
    return staging_results


async def _handle_proposal_edit(websocket: WebSocket, session_id: str, state: ClientState, payload: dict[str, Any]) -> None:
    """Edit a proposal's dry-run payload before approval. Approver-only."""
    if not _can_approve(state):
        await _send_error(
            websocket,
            session_id,
            "forbidden",
            "Editing standup proposals requires the canApproveStandupActions capability.",
        )
        return
    proposal_id = str(payload.get("proposal_id") or payload.get("id") or "").strip()
    if not proposal_id:
        raise ValueError("proposal_id is required")
    patch = payload.get("dry_run_payload")
    if not isinstance(patch, dict):
        raise ValueError("dry_run_payload object is required for proposal.edit")
    proposal = await get_store().edit_proposal_payload(session_id, proposal_id, patch=patch, actor=state.author)
    await manager.broadcast(session_id, {"type": "proposal.updated", "session_id": session_id, "proposal": proposal})


async def _handle_proposal_status(
    websocket: WebSocket, session_id: str, state: ClientState, payload: dict[str, Any], status: str
) -> None:
    # S20.auth.1 — only scrum-master/product-owner (canApproveStandupActions)
    # may approve or reject; everyone else is read-only on the tray.
    if not _can_approve(state):
        await _send_error(
            websocket,
            session_id,
            "forbidden",
            f"Approving/rejecting standup proposals requires the canApproveStandupActions capability "
            f"(you are '{state.author}').",
        )
        return

    proposal_id = str(payload.get("proposal_id") or payload.get("id") or "").strip()
    if not proposal_id:
        raise ValueError("proposal_id is required")

    apply_result: dict[str, Any] | None = None
    if status == "approved":
        # Dry-run apply path: validate any staged Jira edits via Stage-16 tools.
        # STANDUP_DRY_RUN_ONLY (default true) means we never call jira_apply_staged
        # here — approval records a validated, dry-run-only outcome.
        apply_result = await _apply_proposal_dry_run(session_id, proposal_id, state)

    proposal = await get_store().update_proposal_status(
        session_id, proposal_id, status=status, actor=state.author, apply_result=apply_result
    )
    await manager.broadcast(session_id, {"type": "proposal.updated", "session_id": session_id, "proposal": proposal})


async def _apply_proposal_dry_run(session_id: str, proposal_id: str, state: ClientState) -> dict[str, Any]:
    """Run the dry-run apply path for an approved proposal.

    For Jira-edit proposals carrying concrete edits, re-validate the staged
    changes through Stage-16 ``jira_validate_staged`` so the recorded approval
    reflects current validation. Never calls live apply while
    STANDUP_DRY_RUN_ONLY is enabled (the default).
    """
    snapshot = await get_store().snapshot(session_id)
    proposal = next((p for p in snapshot.get("proposals", []) if p.get("id") == proposal_id), None)
    if proposal is None:
        raise KeyError(f"proposal not found: {proposal_id}")

    dry_run_only = _env_bool("STANDUP_DRY_RUN_ONLY", True)
    edits = _jira_edits_from_proposal(proposal)
    if not edits:
        return {"applied": False, "dry_run_only": dry_run_only, "detail": "no Jira edits to validate; recorded as dry-run approval"}

    actor = {"display_name": state.author, "email": state.email}
    issue_keys = [str(edit.get("issue_key")) for edit in edits if edit.get("issue_key")]
    try:
        validation_result = _extract_json_block(
            await _mcp_tool("jira_validate_staged", {"issue_keys": issue_keys, "actor": actor})
        )
        validated = validation_result.get("validated", 0) if isinstance(validation_result, dict) else 0
        return {
            "applied": False,
            "dry_run_only": dry_run_only,
            "validated": validated,
            "issue_keys": issue_keys,
            "validation": validation_result,
            "detail": "validated staged Jira edits; live apply suppressed by STANDUP_DRY_RUN_ONLY"
            if dry_run_only
            else "validated staged Jira edits; apply still requires JIRA_WRITES_ENABLED + Stage-16 apply",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "applied": False,
            "dry_run_only": dry_run_only,
            "error": f"{type(exc).__name__}: {exc}",
            "issue_keys": issue_keys,
            "detail": "validation failed; approval recorded without apply",
        }


async def _send_error(websocket: WebSocket, session_id: str, code: str, message: str) -> None:
    await manager.send(websocket, {"type": "error", "session_id": session_id, "error": {"code": code, "message": message}})
