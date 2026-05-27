"""Stage 31 read-only incoming-ticket intake analysis.

This module intentionally stays connector-shaped but local/deterministic for the
POC: it reads the existing Jira connector sample/list output, identifies tickets
that look like unassigned intake, extracts common request entities, matches the
request to backend-owned standup workflow templates, and returns compact
connector-hub context without performing writes.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any

import standup_templates

AWS_ACCOUNT_RE = re.compile(r"\b(?:aws[-_\s]*account|account)[:#\s-]*([0-9]{12})\b", re.I)
RDS_RE = re.compile(r"\b(?:rds|db|database|instance)[:#\s-]*([a-z][a-z0-9-]{4,63})\b", re.I)
REGION_RE = re.compile(r"\b(?:us|eu|ap|sa|ca|me|af)-(?:north|south|east|west|central|northeast|southeast|southwest)-\d\b", re.I)
TEAM_RE = re.compile(r"\b(?:app[-_\s]*team|team)[:#\s-]*([A-Za-z][A-Za-z0-9_-]{2,40})\b", re.I)
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
DL_RE = re.compile(r"\b(?:dl|distribution[-_\s]*list)[:#\s-]*([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})\b", re.I)
USER_RE = re.compile(r"(?<!\w)@([A-Za-z0-9._-]+)")

NEW_STATUSES = {"new", "triage", "to do", "todo", "open", "backlog"}


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        clean = str(value or "").strip()
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key)
            out.append(clean)
    return out


def extract_entities(text: str) -> dict[str, list[str]]:
    """Extract Stage-31 request entities from free text."""
    return {
        "aws_accounts": _dedupe(AWS_ACCOUNT_RE.findall(text)),
        "rds_instances": _dedupe(RDS_RE.findall(text)),
        "aws_regions": _dedupe([m.group(0) for m in REGION_RE.finditer(text)]),
        "app_team_ids": _dedupe(TEAM_RE.findall(text)),
        "users": _dedupe(USER_RE.findall(text)),
        "emails": _dedupe(EMAIL_RE.findall(text)),
        "distribution_lists": _dedupe(DL_RE.findall(text)),
    }


def _issue_text(issue: dict[str, Any]) -> str:
    parts = [issue.get("key"), issue.get("summary"), issue.get("description"), issue.get("labels"), issue.get("components")]
    return " ".join(str(p) for p in parts if p)


def _is_unassigned_intake(issue: dict[str, Any]) -> bool:
    assignee = str(issue.get("assignee") or "").strip().lower()
    status = str(issue.get("status") or issue.get("state") or "").strip().lower()
    labels = [str(v).lower() for v in issue.get("labels") or []]
    is_unassigned = assignee in {"", "none", "null", "unassigned"}
    is_new = status in NEW_STATUSES or "intake" in labels or "triage" in labels
    return is_unassigned and is_new


def _fallback_intake() -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return [
        {
            "key": "INTAKE-101",
            "summary": "Onboard app-team payments to RDS audit logging in aws account 123456789012 us-east-1",
            "description": "Please onboard team:payments for rds:payments-prod in account 123456789012. Reporter @maya.chen maya.chen@lanGarland.com, DL dl-payments@lanGarland.com.",
            "status": "Triage",
            "assignee": "",
            "reporter": "maya.chen@lanGarland.com",
            "created": now,
            "labels": ["intake", "onboarding", "database"],
        },
        {
            "key": "INTAKE-102",
            "summary": "Consultation request for GitHub branch protection findings on infra repos",
            "description": "Need consultation for app-team platform about branch compliance and ServiceNow change CHG001.",
            "status": "New",
            "assignee": None,
            "reporter": "alex.secops@lanGarland.com",
            "created": now,
            "labels": ["triage", "consultation", "security"],
        },
    ]


def _templates() -> list[dict[str, Any]]:
    payload = standup_templates.payload()
    return [t for t in payload.get("templates", []) if isinstance(t, dict)]


def match_workflow(issue: dict[str, Any], entities: dict[str, list[str]]) -> dict[str, Any]:
    text = _issue_text(issue).lower()
    templates = _templates()
    candidates: list[tuple[float, dict[str, Any], list[str]]] = []
    for template in templates:
        hay = " ".join(str(template.get(k, "")) for k in ("name", "kind", "description", "body_md")).lower()
        score = 0.0
        reasons: list[str] = []
        for token in ("onboard", "on-boarding", "onboarding"):
            if token in text and token in hay:
                score += 0.35; reasons.append("onboarding wording")
        for token in ("consult", "consultation", "guide"):
            if token in text and token in hay:
                score += 0.35; reasons.append("consultation wording")
        for token in ("jira", "confluence", "rds", "database", "github", "servicenow"):
            if token in text and token in hay:
                score += 0.1; reasons.append(f"shared {token} context")
        if entities["aws_accounts"] or entities["rds_instances"]:
            if "rds" in hay or "database" in hay or "onboard" in hay:
                score += 0.2; reasons.append("database/cloud entities present")
        if score:
            candidates.append((min(score, 0.95), template, _dedupe(reasons)))
    if not candidates:
        kind = "onboarding" if any(w in text for w in ("onboard", "access", "setup")) else "consultation" if "consult" in text else "none"
        if kind == "none":
            return {"matched": False, "workflow": None, "confidence": 0.0, "rationale": "No onboarding or consultation template matched."}
        return {"matched": True, "workflow": kind, "confidence": 0.55, "rationale": f"Keyword-only {kind} match; no explicit template available."}
    score, template, reasons = sorted(candidates, key=lambda item: item[0], reverse=True)[0]
    return {"matched": True, "workflow": template.get("name"), "kind": template.get("kind"), "confidence": round(score, 2), "rationale": "; ".join(reasons)}


def _source(status: str, summary: str, items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"status": status, "summary": summary, "items": items or []}


def enrich(issue: dict[str, Any], entities: dict[str, list[str]], connector_summaries: dict[str, Any] | None = None) -> dict[str, Any]:
    summaries = connector_summaries or {}
    text = _issue_text(issue).lower()
    return {
        "aws": _source("available" if entities["aws_accounts"] or entities["rds_instances"] else "no_data", "AWS/RDS clues extracted from ticket text; live connector details are summarized separately.", [{"aws_accounts": entities["aws_accounts"], "rds_instances": entities["rds_instances"], "regions": entities["aws_regions"]}] if (entities["aws_accounts"] or entities["rds_instances"] or entities["aws_regions"]) else []),
        "servicenow": _source("available" if "snow" in text or "chg" in text or "inc" in text else "no_data", "ServiceNow context inferred from ticket text and connector health.", []),
        "github": _source("available" if "github" in text or "repo" in text or "branch" in text else "no_data", "GitHub context inferred from repository/branch keywords.", []),
        "mongo": _source("available", "Mongo read models are available for deeper routed lookups.", []),
        "connector_health": summaries,
    }


async def build_incoming_tickets(jira_issues: list[dict[str, Any]] | None = None, *, limit: int = 10, connector_summaries: dict[str, Any] | None = None, identity_builder: Any | None = None) -> dict[str, Any]:
    candidates = [i for i in (jira_issues or []) if isinstance(i, dict) and _is_unassigned_intake(i)]
    if not candidates and os.environ.get("STANDUP_INCOMING_DEMO", "false").lower() == "true":
        candidates = _fallback_intake()
    tickets: list[dict[str, Any]] = []
    for issue in candidates[: max(1, min(limit, 25))]:
        text = _issue_text(issue)
        entities = extract_entities(text)
        identity = None
        if identity_builder is not None:
            for candidate in [issue.get("reporter"), *entities.get("emails", []), *entities.get("users", [])]:
                if candidate:
                    try:
                        identity = await identity_builder(str(candidate))
                    except Exception as exc:  # noqa: BLE001
                        identity = {"identity": str(candidate), "found": False, "status": f"degraded: {type(exc).__name__}"}
                    if identity and identity.get("found"):
                        break
        tickets.append({
            "key": str(issue.get("key") or issue.get("issue_key") or ""),
            "summary": str(issue.get("summary") or ""),
            "reporter": str(issue.get("reporter") or issue.get("creator") or ""),
            "created": issue.get("created") or issue.get("created_at"),
            "status": str(issue.get("status") or ""),
            "assignee": issue.get("assignee"),
            "entities": entities,
            "workflow_match": match_workflow(issue, entities),
            "enrichment": enrich(issue, entities, connector_summaries),
            "identity_enrichment": identity,
            "proposal": {"status": "proposed", "dry_run": True, "target_service": "workflow", "payload": {"ticket_key": issue.get("key"), "entities": entities, "identity": identity}}, 
        })
    return {"tickets": tickets, "count": len(tickets), "limit": limit, "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "read_only": True}


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [f"# Incoming tickets ({payload.get('count', 0)})", ""]
    for ticket in payload.get("tickets", []):
        match = ticket.get("workflow_match") or {}
        lines.append(f"- **{ticket.get('key')}** {ticket.get('summary')} — {match.get('workflow') or 'no match'} ({match.get('confidence', 0)})")
    return "\n".join(lines)
