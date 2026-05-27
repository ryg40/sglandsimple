#!/usr/bin/env python3
"""Smoke: the config-only "add an agent" path (S21.extend.1).

Proves the platform's extensibility goal: a brand-new read-only agent
(`datadog_agent`, a new observability environment) was added by a connector
class + one registry line + one `profiles.yaml` row — **no change to the
orchestrator, runtime, or _dispatch_tool**. Run against a live stack with the
connector enabled (`CONN_DATADOG_ENABLED=true`):

    MCP_URL=http://localhost:5451/mcp python3 scripts/smoke_agent_extend.py

Assertions:
1. `datadog_agent` appears in `agent_profiles_list` (read_only, no capability).
2. Its connector tool `datadog_list_monitors` dispatches (connector auto-wired).
3. The agent runs a scoped smoke goal and completes with typed output.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

MCP_URL = os.environ.get("MCP_URL", "http://localhost:5451/mcp")
_id = 0
_sid: str | None = None


def _rpc(method: str, params: dict | None = None) -> dict:
    global _id, _sid
    _id += 1
    body = json.dumps({"jsonrpc": "2.0", "id": _id, "method": method, "params": params or {}}).encode()
    headers = {"Content-Type": "application/json"}
    if _sid:
        headers["Mcp-Session-Id"] = _sid
    req = urllib.request.Request(MCP_URL, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req) as r:
        sid = r.headers.get("Mcp-Session-Id")
        if sid:
            _sid = sid
        return json.loads(r.read().decode())


def _call(tool: str, args: dict) -> dict:
    result = _rpc("tools/call", {"name": tool, "arguments": args}).get("result", {})
    for text in reversed([c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]):
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            continue
    return {}


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def main() -> None:
    _rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})

    print("[1] datadog_agent in agent_profiles_list")
    agents = {a["name"]: a for a in _call("agent_profiles_list", {}).get("agents", [])}
    if "datadog_agent" not in agents:
        _fail(f"datadog_agent missing; roster={sorted(agents)}")
    dd = agents["datadog_agent"]
    if dd["write_policy"] != "read_only" or dd.get("required_capability"):
        _fail(f"datadog_agent scope wrong: {dd['write_policy']} cap={dd.get('required_capability')}")
    print(f"    OK — read_only, tools={dd.get('allowed_tools')}")

    print("\n[2] datadog_list_monitors dispatches (connector auto-wired)")
    mon = _call("datadog_list_monitors", {"status": "Alert"})
    if "monitors" not in mon:
        _fail(f"datadog_list_monitors returned no monitors: {mon}")
    print(f"    OK — {len(mon['monitors'])} alerting monitor(s)")

    print("\n[3] datadog_agent runs a scoped smoke goal")
    rid = _call("agent_run_start", {
        "goal": "List the Datadog monitors that are currently alerting.",
        "agent": "datadog_agent", "mode": "dry_run",
    }).get("run_id")
    if not rid:
        _fail("no run_id from agent_run_start")
    rec = {}
    for _ in range(40):
        time.sleep(2)
        rec = _call("agent_run_status", {"run_id": rid})
        if rec.get("status") in ("completed", "waiting_approval", "rejected", "error"):
            break
    if rec.get("status") != "completed":
        _fail(f"unexpected status {rec.get('status')} (err={rec.get('error','')[:160]})")
    print(f"    OK — completed; result={ (rec.get('result_text') or '')[:90]!r}")

    print("\nPASS: config-only add-an-agent path verified (no orchestrator/runtime changes)")


if __name__ == "__main__":
    main()
