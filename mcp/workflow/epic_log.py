"""Epic Confluence documentation log formatter."""

from __future__ import annotations

import datetime
from typing import Any


def render_epic_log(finding: dict[str, Any], epic: dict[str, Any], runs: list[dict[str, Any]]) -> str:
    """Renders highly styled Epic-Log documentation for Confluence."""
    epic_title = epic.get("title", "Epic Logs")
    jira_key = epic.get("jira_key", "MOCK-1")
    reg = finding.get("regulation", "SOX-404")

    md = [
        f"# Epic-Log: {epic_title} ({jira_key})",
        f"**Last Sync Date:** {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC",
        "",
        "## Regulatory Compliance Scope",
        f"- **Audit Regulation:** {reg}",
        f"- **Requirement Gaps Addressed:** {finding.get('requirement', 'Database Audit Logs')}",
        "",
        "## Active Work Items Tracking Status",
    ]

    if not runs:
        md += ["*No complete compliance runner runs logged yet.*"]
    else:
        md.append("| Step / Run | Artifacts Created | Status | Date |")
        md.append("|---|---|---|---|")
        for idx, run in enumerate(runs):
            run_id = run.get("_id", "unknown-run")
            status = run.get("status", "running")
            state_idx = run.get("step_index", 0)
            arts = str(run.get("artifacts", {}))
            md.append(f"| Run-{run_id[:8]} (Step {state_idx}) | {arts} | {status.upper()} | {datetime.datetime.utcnow().strftime('%Y-%m-%d')} |")

    md += [
        "",
        "## Audit Verification References",
        "- Verification Engine Link: [Smoke Test Verification Catalog](https://grafana.enterprise.internal)",
        f"\n*Last updated automatically by compliance orchestrator daemon.*"
    ]

    return "\n".join(md)
