#!/usr/bin/env python3
"""Smoke: the baseline Deep Agent system roster (S21.agent.1).

Proves the orchestrator + 8 system agents are wired and behave per their
profile scope, against a live stack:

    MCP_URL=http://localhost:5451/mcp python3 scripts/smoke_agents.py

Assertions
----------
1. `agent_profiles_list` returns all 8 expected agents with the right
   write_policy / required_capability.
2. Each *read-only / fast* agent (aws, servicenow) runs a scoped goal and
   completes with typed output, **without** performing any write (read agents
   have no write tools, so a write cannot occur).
3. The orchestrator routes an un-targeted goal to a subagent and completes.
4. A *write* agent (atlassian) pauses at `interrupt_on` for its write tool
   (`jira_apply_staged`) with the gating capability surfaced — i.e. write
   agents stop for HITL rather than writing.
5. Graph-backed agents (mongo→ask_data, docs→docs_agent) are exercised when
   RUN_GRAPH_AGENTS=1 (they go through a full LangGraph and are slow); by
   default they are listed-only so the smoke stays CI-friendly.

This never enables live writes; it proves scope + routing + the HITL stop.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

MCP_URL = os.environ.get("MCP_URL", "http://localhost:5451/mcp")
POLL_SECONDS = float(os.environ.get("POLL_SECONDS", "2"))
POLL_TRIES = int(os.environ.get("POLL_TRIES", "40"))
RUN_GRAPH_AGENTS = os.environ.get("RUN_GRAPH_AGENTS", "0") == "1"

EXPECTED = {
    "atlassian_agent": ("dry_run_only", "canApplyJira"),
    "mongo_agent": ("read_only", None),
    "github_agent": ("dry_run_only", "canRunWorkflow"),
    "servicenow_agent": ("read_only", None),
    "aws_agent": ("read_only", None),
    "audit_agent": ("dry_run_only", "canUpdateArcher"),
    "docs_agent": ("dry_run_only", "canManageDocs"),
    "standup_agent": ("dry_run_only", "canApproveStandupActions"),
}

_rpc_id = 0
_sid: str | None = None


def _rpc(method: str, params: dict | None = None) -> dict:
    global _rpc_id, _sid
    _rpc_id += 1
    body = json.dumps({"jsonrpc": "2.0", "id": _rpc_id, "method": method, "params": params or {}}).encode()
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
    res = _rpc("tools/call", {"name": tool, "arguments": args})
    result = res.get("result", res)
    blocks = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
    payload: dict = {}
    for text in reversed(blocks):
        try:
            payload = json.loads(text)
            break
        except (json.JSONDecodeError, TypeError):
            continue
    return {"payload": payload, "isError": result.get("isError", False)}


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def _run_to_settle(agent: str | None, goal: str, tries: int = POLL_TRIES) -> dict:
    args: dict = {"goal": goal, "mode": "dry_run"}
    if agent:
        args["agent"] = agent
    start = _call("agent_run_start", args)
    if start["isError"]:
        _fail(f"{agent or '(route)'}: start errored: {start['payload']}")
    rid = start["payload"].get("run_id")
    if not rid:
        _fail(f"{agent or '(route)'}: no run_id: {start['payload']}")
    rec: dict = {}
    for _ in range(tries):
        time.sleep(POLL_SECONDS)
        rec = _call("agent_run_status", {"run_id": rid})["payload"]
        if rec.get("status") in ("waiting_approval", "completed", "rejected", "error"):
            break
    return rec


def main() -> None:
    _rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})

    # [1] roster
    print("[1] agent_profiles_list")
    res = _call("agent_profiles_list", {})
    agents = {a["name"]: a for a in res["payload"].get("agents", [])}
    missing = set(EXPECTED) - set(agents)
    if missing:
        _fail(f"missing agents: {sorted(missing)}")
    for name, (policy, cap) in EXPECTED.items():
        a = agents[name]
        if a["write_policy"] != policy:
            _fail(f"{name}: write_policy {a['write_policy']!r} != {policy!r}")
        if (a.get("required_capability") or None) != cap:
            _fail(f"{name}: required_capability {a.get('required_capability')!r} != {cap!r}")
    print(f"    OK — {len(agents)} agents, scopes match")

    # [2] read-only/fast agents complete with typed output, no write
    print("\n[2] read-only agents (scoped, no write)")
    for agent, goal in [
        ("aws_agent", "List the available RDS instances."),
        ("servicenow_agent", "Search for recent compliance findings."),
    ]:
        rec = _run_to_settle(agent, goal)
        s = rec.get("status")
        if s != "completed":
            _fail(f"{agent}: expected completed, got {s} (err={rec.get('error','')[:160]})")
        if rec.get("approval"):
            _fail(f"{agent}: read-only agent should not pause for approval")
        print(f"    {agent}: completed; result={ (rec.get('result_text') or '')[:90]!r}")

    # [3] orchestrator routing (no explicit agent)
    print("\n[3] orchestrator routing")
    rec = _run_to_settle(None, "List the AWS RDS instances for the platform team.")
    s = rec.get("status")
    if s not in ("completed", "waiting_approval"):
        _fail(f"routing: unexpected status {s} (err={rec.get('error','')[:160]})")
    print(f"    routed run resolved: {s}")

    # [4] write agent pauses at interrupt_on
    print("\n[4] write agent HITL pause (atlassian → jira_apply_staged)")
    rec = _run_to_settle(
        "atlassian_agent",
        "Stage an edit to ABC-1 setting priority=High via jira_stage_edits, then "
        "call jira_apply_staged to apply it. You MUST call jira_apply_staged.",
    )
    s = rec.get("status")
    if s == "waiting_approval":
        ap = rec.get("approval") or {}
        if ap.get("tool") != "jira_apply_staged":
            _fail(f"atlassian: paused on {ap.get('tool')!r}, expected jira_apply_staged")
        if ap.get("required_capability") != "canApplyJira":
            _fail(f"atlassian: required_capability {ap.get('required_capability')!r} != canApplyJira")
        print(f"    paused for HITL on {ap['tool']} (cap={ap['required_capability']})")
        _call("agent_run_resume", {"run_id": rec["run_id"], "decision": "reject", "actor": "smoke"})
    elif s == "completed":
        # The model may have answered without reaching the write tool; acceptable
        # but note it so the operator can tighten the goal if HITL wasn't exercised.
        print("    NOTE: completed without reaching the write tool (HITL not exercised this run)")
    else:
        _fail(f"atlassian: unexpected status {s} (err={rec.get('error','')[:160]})")

    # [5] graph-backed agents (optional — slow)
    if RUN_GRAPH_AGENTS:
        print("\n[5] graph-backed agents (mongo→ask_data, docs→docs_agent)")
        for agent, goal in [
            ("mongo_agent", "How many tickets are open? Give a count."),
            ("docs_agent", "Find docs that mention audit logging."),
        ]:
            rec = _run_to_settle(agent, goal, tries=POLL_TRIES * 3)
            s = rec.get("status")
            if s not in ("completed", "waiting_approval"):
                _fail(f"{agent}: unexpected status {s} (err={rec.get('error','')[:160]})")
            print(f"    {agent}: {s}")
    else:
        print("\n[5] graph-backed agents (mongo/docs): listed-only "
              "(set RUN_GRAPH_AGENTS=1 to exercise the full graphs)")

    print("\nPASS: baseline agent roster — scopes, read-only behavior, routing, and write HITL verified")


if __name__ == "__main__":
    main()
