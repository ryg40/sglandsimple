#!/usr/bin/env python3
"""Smoke test for the Stage 20 standup websocket backend.

Usage:
  scripts/smoke_standup_ws.py [ws://localhost:5452/api/standup/ws/smoke]

Covers two-client join/chat, link/mention extraction, dry-run agent
summarization + proposal persistence, and the Stage-20 RBAC approval gate:
a non-approver (viewer) is rejected with a 'forbidden' error, while an
approver (admin) flips the proposal to 'approved' with a recorded actor and a
dry-run-only apply result.

Auth model: the standup websocket requires a resolved Stage-19 identity unless
AUTH_MODE=disabled. In the default 'basic' mode this script authenticates the
two clients with HTTP Basic Auth using seeded POC users:
  - viewer:   avery.stone@lanGarland.com   (sg_all_users → no approval)
  - approver: simone.patel@lanGarland.com  (sg_sec_admin → canApproveStandupActions)
Override the password with STANDUP_SMOKE_PASSWORD (default 'changeme-poc').
Set STANDUP_SMOKE_AUTH=0 to skip auth headers (only works when the target
stack runs AUTH_MODE=disabled).

Requires the `websockets` package, which is available in the web image through
uvicorn[standard].
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import time
import urllib.request
from typing import Any

try:
    import websockets
except ImportError as exc:  # pragma: no cover - operator guidance
    raise SystemExit("Missing dependency: install/use an environment with the 'websockets' package") from exc


VIEWER_USER = os.environ.get("STANDUP_SMOKE_VIEWER", "avery.stone@lanGarland.com")
APPROVER_USER = os.environ.get("STANDUP_SMOKE_APPROVER", "simone.patel@lanGarland.com")
SMOKE_PASSWORD = os.environ.get("STANDUP_SMOKE_PASSWORD", "changeme-poc")
USE_AUTH = os.environ.get("STANDUP_SMOKE_AUTH", "1").strip().lower() not in {"0", "false", "no"}


def _default_url() -> str:
    return f"ws://localhost:5452/api/standup/ws/smoke-{int(time.time())}"


def _snapshot_url(ws_url: str) -> str:
    base, session_id = ws_url.split("/api/standup/ws/", 1)
    session_id = session_id.split("?", 1)[0]
    http_base = base.replace("ws://", "http://", 1).replace("wss://", "https://", 1)
    return f"{http_base}/api/standup/sessions/{session_id}/snapshot"


def _basic_headers(username: str) -> dict[str, str]:
    if not USE_AUTH:
        return {}
    token = base64.b64encode(f"{username}:{SMOKE_PASSWORD}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


async def _send(ws: Any, event_type: str, **payload: Any) -> None:
    await ws.send(json.dumps({"type": event_type, "payload": payload}))


async def _recv_until(ws: Any, *event_types: str, timeout: float = 5.0) -> dict[str, Any]:
    wanted = set(event_types)
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"timed out waiting for {' or '.join(wanted)}")
        raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        event = json.loads(raw)
        if event.get("type") in wanted:
            return event


async def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else _default_url()
    viewer_headers = _basic_headers(VIEWER_USER)
    approver_headers = _basic_headers(APPROVER_USER)

    async with websockets.connect(url, extra_headers=approver_headers) as approver, websockets.connect(
        url, extra_headers=viewer_headers
    ) as viewer:
        await _recv_until(approver, "session.snapshot")
        await _recv_until(viewer, "session.snapshot")

        await _send(approver, "join", title="Smoke standup")
        await _send(viewer, "join")
        await _recv_until(approver, "presence.update")
        await _recv_until(viewer, "presence.update")

        # --- chat + link/mention extraction -------------------------------- #
        body = "Please follow up on ABC-123 with @bob https://github.com/example/repo/pull/1"
        await _send(approver, "chat.message", body=body)
        chat = await _recv_until(viewer, "chat.message")
        message = chat.get("message", {})
        assert message.get("body") == body, message
        assert "bob" in message.get("mentions", []), message
        assert "ABC-123" in message.get("jira_keys", []), message

        # --- dry-run agent summarize → proposal persistence ---------------- #
        await _send(approver, "agent.summarize", trigger="smoke", selected_issues=[{"key": "ABC-123"}])
        proposed = await _recv_until(viewer, "proposal.updated", timeout=30)
        await _recv_until(approver, "proposal.updated", timeout=30)
        proposal = proposed.get("proposal", {})
        proposal_id = proposal.get("id")
        assert proposal_id, proposed
        assert proposal.get("status") == "proposed", proposal
        assert proposal.get("dry_run") is True, proposal
        assert isinstance(proposal.get("dry_run_payload"), dict), proposal
        assert isinstance(proposal.get("validation_state"), dict), proposal

        # --- RBAC: viewer (non-approver) cannot approve -------------------- #
        if USE_AUTH:
            await _send(viewer, "proposal.approve", proposal_id=proposal_id)
            err = await _recv_until(viewer, "error", timeout=10)
            assert err.get("error", {}).get("code") == "forbidden", err
            print(f"  rbac: viewer approve denied ({err['error'].get('message','')[:60]}…)")

        # --- RBAC: approver (admin) approves, dry-run only ----------------- #
        await _send(approver, "proposal.approve", proposal_id=proposal_id)
        # Both clients receive the broadcast; find the approved one.
        approved = None
        for client in (approver, viewer):
            evt = await _recv_until(client, "proposal.updated", timeout=15)
            if evt.get("proposal", {}).get("id") == proposal_id and evt["proposal"].get("status") == "approved":
                approved = evt["proposal"]
        assert approved is not None, "no approved proposal.updated received"
        assert approved.get("status") == "approved", approved
        approval = approved.get("approval") or {}
        assert approval.get("decision") == "approved", approval
        assert approval.get("actor"), approval
        assert approval.get("applied") is False, approval
        assert approval.get("dry_run_only") is True, approval
        print(f"  rbac: approver approved proposal (actor={approval.get('actor')}, applied=False)")

        # --- snapshot persistence (authenticated GET) ---------------------- #
        req = urllib.request.Request(_snapshot_url(url), headers=_basic_headers(APPROVER_USER))
        with urllib.request.urlopen(req, timeout=5) as response:
            snapshot = json.loads(response.read().decode("utf-8"))
        persisted = next((p for p in snapshot.get("proposals", []) if p.get("id") == proposal_id), None)
        assert persisted is not None, snapshot
        assert persisted.get("status") == "approved", persisted

    print(f"standup websocket smoke passed: {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
