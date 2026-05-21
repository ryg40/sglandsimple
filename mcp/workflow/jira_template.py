"""Jira ticket generation payload builder."""

from __future__ import annotations

from typing import Any


def render_jira_story(finding: dict[str, Any], epic: dict[str, Any]) -> dict[str, Any]:
    """Produce structured Jira stories as compliance proof items."""
    jira_key = epic.get("jira_key", "MOCK-1")
    project_key = jira_key.split("-")[0] if "-" in jira_key else "MOCK"

    req = finding.get("requirement", "Compliance requirement details")
    reg = finding.get("regulation", "SOX-404")
    severity = finding.get("severity", "high")

    summary = f"[{jira_key}] Implement control: {req[:60]}..."
    description = (
        f"**Regulation Compliance Context:** {reg}\n"
        f"**Requirement:** {req}\n"
        f"**Severity Level:** {severity.upper()}\n\n"
        f"This issue logs the technical implementation of database audit controls. "
        f"Run security scanning and deliver proof of logs."
    )

    return {
        "project": {"key": project_key},
        "summary": summary,
        "description": description,
        "issuetype": {"name": "Story"},
        "customfield_epic_link": jira_key,
    }
