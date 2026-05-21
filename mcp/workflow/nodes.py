"""Workflow node execution handlers."""

from __future__ import annotations

import datetime
from typing import Any

from bson import ObjectId

import db as dbmod
from connectors import get_connector

from .jira_template import render_jira_story
from .pr_template import render_pr_template
from .epic_log import render_epic_log


async def capture_finding(state: dict[str, Any]) -> dict[str, Any]:
    """Step 1 is discovery: Fetch finding metadata."""
    finding_id = state["finding_id"]
    finding = await dbmod.find_workflow("audit_findings", finding_id)
    if not finding:
        raise ValueError(f"Finding not found: {finding_id}")

    artifacts = dict(state.get("artifacts") or {})
    artifacts["finding"] = finding

    return {
        "finding_id": finding_id,
        "epic_id": finding.get("epic_id", ""),
        "step_index": 1,
        "artifacts": artifacts,
        "status": "running"
    }


async def link_epic(state: dict[str, Any]) -> dict[str, Any]:
    """Step 2: Link RDS/GCP database level epics."""
    finding_id = state["finding_id"]
    finding = state["artifacts"]["finding"]
    epic_id = finding.get("epic_id")

    if not epic_id:
        # Fallback search or fallback dummy
        epic_id = "epic-rds-001"

    epic = await dbmod.find_workflow("epics", epic_id)
    if not epic:
        raise ValueError(f"Epic not found in db: {epic_id}")

    artifacts = dict(state.get("artifacts") or {})
    artifacts["epic"] = epic

    return {
        "finding_id": finding_id,
        "epic_id": epic_id,
        "step_index": 2,
        "artifacts": artifacts,
        "status": "running"
    }


async def generate_ticket(state: dict[str, Any]) -> dict[str, Any]:
    """Step 3: Generate a Best-Practice Jira compliance Issue ticket."""
    finding = state["artifacts"]["finding"]
    epic = state["artifacts"]["epic"]

    payload = render_jira_story(finding, epic)

    jira_conn = get_connector("jira")
    is_live = dbmod.WORKFLOW_WRITES_ENABLED and jira_conn and jira_conn.enabled

    ticket_key = "MOCK-123"
    if is_live and jira_conn:
        try:
            res = await jira_conn.dispatch("jira_create_issue", payload)
            # Try to grab payload output
            import json
            data = json.loads(res["content"][0]["text"])
            ticket_key = data.get("key", "MOCK-123")
        except Exception as e:  # noqa: BLE001
            print(f"[workflow nodes] jira live ticket call failed: {e}", flush=True)

    artifacts = dict(state.get("artifacts") or {})
    artifacts["ticket_payload"] = payload
    artifacts["ticket_key"] = ticket_key

    # Save work_item doc to database if writes are enabled
    if dbmod.WORKFLOW_WRITES_ENABLED:
        try:
            await dbmod.insert_workflow("work_items", {
                "finding_id": state["finding_id"],
                "epic_id": state["epic_id"],
                "jira_key": ticket_key,
                "type": "story",
                "status": "completed",
                "created_at": datetime.datetime.utcnow().isoformat(),
            }, source="workflow_ticket")
        except Exception as e:  # noqa: BLE001
            print(f"[workflow nodes] mongo insert work_items failed: {e}", flush=True)

    return {
        "finding_id": state["finding_id"],
        "epic_id": state["epic_id"],
        "step_index": 3,
        "artifacts": artifacts,
        "status": "running"
    }


async def coding_branch(state: dict[str, Any]) -> dict[str, Any]:
    """Step 4: Generate compliance branch name format."""
    finding = state["artifacts"]["finding"]
    ticket_key = state["artifacts"].get("ticket_key", "MOCK-123")

    pr_spec = render_pr_template(ticket_key, finding.get("requirement", ""))

    artifacts = dict(state.get("artifacts") or {})
    artifacts["branch_name"] = pr_spec["branch"]
    artifacts["pr_spec"] = pr_spec

    return {
        "finding_id": state["finding_id"],
        "epic_id": state["epic_id"],
        "step_index": 4,
        "artifacts": artifacts,
        "status": "running"
    }


async def open_pr(state: dict[str, Any]) -> dict[str, Any]:
    """Step 5: File compliance GitHub PR with checklists and required checks."""
    branch_name = state["artifacts"]["branch_name"]
    pr_spec = state["artifacts"]["pr_spec"]

    github_conn = get_connector("github")
    is_live = dbmod.WORKFLOW_WRITES_ENABLED and github_conn and github_conn.enabled

    pr_url = "https://github.com/org/repo/pull/123"
    pr_number = 123
    if is_live and github_conn:
        try:
            res = await github_conn.dispatch("github_open_pr", {
                "repo": "enterprise-compliance-db",
                "title": pr_spec["title"],
                "head": branch_name,
                "base": "main",
                "body": pr_spec["body"],
            })
            import json
            data = json.loads(res["content"][0]["text"])
            pr_url = data.get("url", pr_url)
            pr_number = data.get("number", pr_number)
        except Exception as e:  # noqa: BLE001
            print(f"[workflow nodes] github live PR failed: {e}", flush=True)

    artifacts = dict(state.get("artifacts") or {})
    artifacts["pr_url"] = pr_url
    artifacts["pr_number"] = pr_number

    # Save PR record doc to database if writes are enabled
    if dbmod.WORKFLOW_WRITES_ENABLED:
        try:
            await dbmod.insert_workflow("pr_records", {
                "work_item_id": "work-item-" + str(state["finding_id"]),
                "epic_id": state["epic_id"],
                "pr_number": pr_number,
                "branch": branch_name,
                "status": "open",
                "url": pr_url,
                "created_at": datetime.datetime.utcnow().isoformat(),
            }, source="workflow_pr")
        except Exception as e:  # noqa: BLE001
            print(f"[workflow nodes] mongo insert pr_records failed: {e}", flush=True)

    return {
        "finding_id": state["finding_id"],
        "epic_id": state["epic_id"],
        "step_index": 5,
        "artifacts": artifacts,
        "status": "running"
    }


async def post_approval_docs(state: dict[str, Any]) -> dict[str, Any]:
    """Step 6: Write epic Confluence compliance status summary document."""
    finding = state["artifacts"]["finding"]
    epic = state["artifacts"]["epic"]

    # Gather any recent workflow run logs to include in wiki logs summary
    recent_runs = []
    if dbmod.WORKFLOW_WRITES_ENABLED:
        try:
            recent_runs = await dbmod.list_workflow_runs(finding_id=state["finding_id"], limit=5)
        except Exception as e:  # noqa: BLE001
            print(f"[workflow nodes] list workflow runs failed: {e}", flush=True)

    doc_text = render_epic_log(finding, epic, recent_runs)

    confluence_conn = get_connector("confluence")
    is_live = dbmod.WORKFLOW_WRITES_ENABLED and confluence_conn and confluence_conn.enabled

    confluence_url = "https://confluence.example.com/pages/RDS-Log-Audit"
    if is_live and confluence_conn:
        try:
            res = await confluence_conn.dispatch("confluence_create_page", {
                "title": f"Epic Compliance Logs: {epic.get('jira_key', 'RDS-1')}",
                "space": "COMP",
                "body": doc_text,
            })
            import json
            data = json.loads(res["content"][0]["text"])
            confluence_url = data.get("url", confluence_url)
        except Exception as e:  # noqa: BLE001
            print(f"[workflow nodes] confluence page create failed: {e}", flush=True)

    artifacts = dict(state.get("artifacts") or {})
    artifacts["confluence_doc_text"] = doc_text
    artifacts["confluence_url"] = confluence_url

    # Save doc records to database if writes are enabled
    if dbmod.WORKFLOW_WRITES_ENABLED:
        try:
            await dbmod.insert_workflow("doc_records", {
                "epic_id": state["epic_id"],
                "finding_id": state["finding_id"],
                "title": f"Epic Compliance Logs: {epic.get('jira_key', 'RDS-1')}",
                "confluence_url": confluence_url,
                "status": "published",
                "created_at": datetime.datetime.utcnow().isoformat(),
            }, source="workflow_doc")
        except Exception as e:  # noqa: BLE001
            print(f"[workflow nodes] mongo insert doc_records failed: {e}", flush=True)

    return {
        "finding_id": state["finding_id"],
        "epic_id": state["epic_id"],
        "step_index": 6,
        "artifacts": artifacts,
        "status": "completed"
    }
