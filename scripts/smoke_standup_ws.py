#!/usr/bin/env python3
"""Smoke test for the Stage 20 standup websocket backend.

Usage:
  scripts/smoke_standup_ws.py [ws://localhost:5452/api/standup/ws/smoke]

Requires the `websockets` package, which is available in the web image through
uvicorn[standard].
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from typing import Any

try:
    import websockets
except ImportError as exc:  # pragma: no cover - operator guidance
    raise SystemExit("Missing dependency: install/use an environment with the 'websockets' package") from exc


def _default_url() -> str:
    return f"ws://localhost:5452/api/standup/ws/smoke-{int(time.time())}"


async def _send(ws: Any, event_type: str, **payload: Any) -> None:
    await ws.send(json.dumps({"type": event_type, "payload": payload}))


async def _recv_until(ws: Any, event_type: str, *, timeout: float = 5.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"timed out waiting for {event_type}")
        raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        event = json.loads(raw)
        if event.get("type") == event_type:
            return event


async def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else _default_url()
    async with websockets.connect(f"{url}?author=alice") as alice, websockets.connect(f"{url}?author=bob") as bob:
        await _recv_until(alice, "session.snapshot")
        await _recv_until(bob, "session.snapshot")

        await _send(alice, "join", author="alice", title="Smoke standup")
        await _send(bob, "join", author="bob")
        await _recv_until(alice, "presence.update")
        await _recv_until(bob, "presence.update")

        body = "Please follow up on ABC-123 with @bob https://github.com/example/repo/pull/1"
        await _send(alice, "chat.message", body=body)
        chat = await _recv_until(bob, "chat.message")
        message = chat.get("message", {})
        assert message.get("body") == body, message
        assert "bob" in message.get("mentions", []), message
        assert "ABC-123" in message.get("jira_keys", []), message

        await _send(bob, "agent.summarize")
        proposed = await _recv_until(alice, "proposal.updated")
        await _recv_until(bob, "proposal.updated")
        proposal_id = proposed.get("proposal", {}).get("id")
        assert proposal_id, proposed

        await _send(alice, "proposal.approve", proposal_id=proposal_id)
        approved = await _recv_until(bob, "proposal.updated")
        assert approved.get("proposal", {}).get("status") == "approved", approved

    print(f"standup websocket smoke passed: {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
