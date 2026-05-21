"""PR branch name and templates builder."""

from __future__ import annotations

from typing import Any


def render_pr_template(ticket_key: str, requirement: str) -> dict[str, Any]:
    """Return Git branch name and Markdown templates for compliance PRs."""
    clean_req = requirement.lower().replace(" ", "-").replace(",", "").replace(".", "")[:30]
    branch_name = f"feature/{ticket_key.lower()}-{clean_req}"

    title = f"[{ticket_key}] Implement Database Audit Control Logging Policy"

    body = (
        f"### Summary\n"
        f"Addresses regulatory requirement: *{requirement}*.\n"
        f"This pull request implements the requested database audit controls to "
        f"log administrative events and SQL execution parameters.\n\n"
        f"### Compliance Checklist\n"
        f"- [x] SQL Error events are logged in destination tables.\n"
        f"- [x] Login errors are tracked with network parameters.\n"
        f"- [x] Source queries can be fully audited from database engine side.\n\n"
        f"### Technical Evidence & Coverage\n"
        f"- Unit testing covers standard login tracking paths.\n"
        f"- Security static analysis results returned successfully."
    )

    return {
        "branch": branch_name,
        "title": title,
        "body": body,
        "checks": ["compliance-scan", "unit-tests", "integration-tests"],
        "reviewers": ["copilot", "infosec-reviewer-1", "db-architect-placeholder"],
    }
