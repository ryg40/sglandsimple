"""FastAPI routes for Stage 20 standup session snapshots and websocket fanout."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from standup_store import get_store

router = APIRouter()


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


def _header_identity(websocket: WebSocket) -> str:
    for header in ("x-forwarded-user", "x-user", "x-auth-request-user"):
        value = websocket.headers.get(header)
        if value:
            return value
    return websocket.query_params.get("author") or "anonymous"


@dataclass
class ClientState:
    client_id: str
    session_id: str
    author: str
    typing: bool = False


class StandupConnectionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, dict[WebSocket, ClientState]] = {}

    async def connect(self, websocket: WebSocket, session_id: str) -> ClientState:
        await websocket.accept()
        state = ClientState(client_id=uuid.uuid4().hex, session_id=session_id, author=_header_identity(websocket))
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
                "typing": state.typing,
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
async def standup_snapshot(session_id: str) -> JSONResponse:
    snapshot = await get_store().snapshot(session_id)
    snapshot["presence"] = {"participants": manager.participants(session_id)}
    return JSONResponse(snapshot)


@router.websocket("/api/standup/ws/{session_id}")
async def standup_ws(websocket: WebSocket, session_id: str) -> None:
    if not _env_bool("STANDUP_WS_ENABLED", True):
        await websocket.close(code=1008, reason="standup websocket disabled")
        return

    state = await manager.connect(websocket, session_id)
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
                    await _handle_agent_summarize(session_id, state)
                elif event_type == "proposal.approve":
                    await _handle_proposal_status(session_id, state, payload, "approved")
                elif event_type == "proposal.reject":
                    await _handle_proposal_status(session_id, state, payload, "rejected")
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
    author = str(payload.get("author") or payload.get("user") or state.author or "anonymous").strip() or "anonymous"
    state.author = author
    snapshot = await get_store().touch_session(
        session_id,
        title=payload.get("title"),
        sprint=payload.get("sprint"),
        epic_keys=payload.get("epic_keys"),
        created_by=author,
    )
    snapshot["presence"] = {"participants": manager.participants(session_id)}
    await manager.send(websocket, {"type": "session.snapshot", "session_id": session_id, "snapshot": snapshot})
    await manager.broadcast_presence(session_id)


async def _handle_chat_message(session_id: str, state: ClientState, payload: dict[str, Any]) -> None:
    body = str(payload.get("body") or payload.get("text") or payload.get("content") or "")
    kind = str(payload.get("kind") or "chat")
    message = await get_store().add_message(session_id, author=state.author, body=body, kind=kind)
    await manager.broadcast(session_id, {"type": "chat.message", "session_id": session_id, "message": message})


async def _handle_typing(session_id: str, state: ClientState, payload: dict[str, Any]) -> None:
    state.typing = bool(payload.get("typing", True))
    await manager.broadcast_presence(session_id)


async def _handle_agent_summarize(session_id: str, state: ClientState) -> None:
    proposal = await get_store().create_summary_placeholder(session_id, actor=state.author)
    await manager.broadcast(session_id, {"type": "proposal.updated", "session_id": session_id, "proposal": proposal})


async def _handle_proposal_status(session_id: str, state: ClientState, payload: dict[str, Any], status: str) -> None:
    proposal_id = str(payload.get("proposal_id") or payload.get("id") or "").strip()
    if not proposal_id:
        raise ValueError("proposal_id is required")
    proposal = await get_store().update_proposal_status(session_id, proposal_id, status=status, actor=state.author)
    await manager.broadcast(session_id, {"type": "proposal.updated", "session_id": session_id, "proposal": proposal})


async def _send_error(websocket: WebSocket, session_id: str, code: str, message: str) -> None:
    await manager.send(websocket, {"type": "error", "session_id": session_id, "error": {"code": code, "message": message}})
