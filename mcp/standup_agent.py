"""Stage 20 standup helper: chat link parsing + dry-run proposal planning.

This module is intentionally side-effect free: it does not persist sessions and
never writes to Jira/Confluence/etc. It only turns standup chat/context into
structured, proposed follow-ups that a later HITL path can review and stage via
existing Stage-16 Jira tools.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from llm import llm_model, structured
from workflow.jira_template import render_jira_story


DEFAULT_SUPPORTED_MODELS = {
    # Current local default used by this stack.
    "qwen3.6-27b",
    # Stage-17 builder model; safe for structured JSON planning when selected.
    "Qwen3.6-35B-A3B-APEX-MTP-I-Balanced",
    # Copilot/hosted-model candidates documented as known-good for tool/JSON use.
    "gpt-4.1",
    "claude-sonnet-4.5",
}

URL_RE = re.compile(r"https?://[^\s<>\]\)\"']+", re.IGNORECASE)
MENTION_RE = re.compile(r"(?<!\w)@([A-Za-z0-9._-]+)")
JIRA_KEY_RE = re.compile(r"(?<![A-Z0-9])([A-Z][A-Z0-9]+-\d+)(?![A-Z0-9])")
TRAILING_URL_PUNCT = ".,;:!?"
DEFAULT_STANDUP_LABELS = ["standup-follow-up", "dry-run", "agent-proposed"]
ACCEPTANCE_CRITERIA_FORMAT = [
    "Given the standup context and linked evidence, when the owner starts the work, then the related Jira/Confluence/SNOW/Archer/GitHub references are reviewed and attached.",
    "Given the implementation is complete, when it is reviewed, then validation evidence or screenshots are linked back to the Jira issue.",
    "Given the work affects compliance proof, when it is closed, then the acceptance notes identify the control, risk, or blocker resolved.",
]


class UnsupportedStandupModel(RuntimeError):
    """Raised before an agent call when the configured planner model is unsafe."""


class StandupLink(BaseModel):
    url: str
    service: str = "web"
    label: str = ""
    jira_key: str | None = None


class StandupChatMessage(BaseModel):
    id: str = ""
    author: str = "unknown"
    body: str
    kind: str = "chat"
    created_at: str | None = None
    links: list[StandupLink] = Field(default_factory=list)
    mentions: list[str] = Field(default_factory=list)
    jira_keys: list[str] = Field(default_factory=list)


class StandupLinkContext(BaseModel):
    messages: list[StandupChatMessage] = Field(default_factory=list)
    links: list[StandupLink] = Field(default_factory=list)
    mentions: list[str] = Field(default_factory=list)
    jira_keys: list[str] = Field(default_factory=list)
    selected_issue_keys: list[str] = Field(default_factory=list)


class StandupItem(BaseModel):
    text: str
    source_message_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.5


class StandupProposal(BaseModel):
    id: str = ""
    type: str = Field(description="new_jira_work, jira_edit, meeting_followup, service_association, doc_link, risk_blocker")
    target_service: str = "jira"
    title: str
    rationale: str = ""
    dry_run_payload: dict[str, Any] = Field(default_factory=dict)
    source_message_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.5
    status: str = "proposed"
    dry_run: bool = True


class StandupAgentResult(BaseModel):
    summary: str = ""
    decisions: list[StandupItem] = Field(default_factory=list)
    risks_blockers: list[StandupItem] = Field(default_factory=list)
    follow_ups: list[StandupItem] = Field(default_factory=list)
    service_associations: list[StandupItem] = Field(default_factory=list)
    proposals: list[StandupProposal] = Field(default_factory=list)


SYSTEM_PROMPT = """You are the Stage 20 Standup Jira cockpit follow-up analyst.

Convert standup chat and selected Jira context into concise, structured meeting
outputs. Safety rules:
- Never claim that Jira, Confluence, Archer, ServiceNow, GitHub, Snowflake, or
  Mongo was mutated.
- Every proposal must be status "proposed" and dry_run true.
- Existing Jira edits must target only existing issue keys from the chat or
  selected_issue_keys, and may only use fields status, assignee, priority,
  story_points, summary, or duedate.
- New Jira work must be a draft payload suitable for later review, not a live
  create call. Use the supplied story_template_context: summary/description
  shape, acceptance_criteria format, labels, priority/story_points guidance,
  epic/workflow docs, and relevant Confluence/doc links.
- For new_jira_work proposals, dry_run_payload should include summary,
  description, issue_type, labels, priority, story_points, acceptance_criteria,
  epic_link when available, related_links/doc_links when relevant, and dry_run.
- If chat is vague (for example "the RDS thing"), use selected Jira rows and
  recently pasted links as context, and lower confidence rather than inventing.
- Include source_message_ids and rationale for every proposal.
"""


def _configured_supported_models() -> set[str]:
    raw = os.environ.get("STANDUP_AGENT_SUPPORTED_MODELS")
    if not raw:
        return set(DEFAULT_SUPPORTED_MODELS)
    return {m.strip() for m in raw.split(",") if m.strip()}


def assert_supported_model(role: str = "planner") -> str:
    """Return the model id for role, or fail fast before issuing an LLM call."""
    model = llm_model(role)
    supported = _configured_supported_models()
    if "codex" in model.lower() or model not in supported:
        raise UnsupportedStandupModel(
            f"Unsupported standup planner model {model!r}. "
            f"Set PLANNER_MODEL/UPSTREAM_MODEL to one of {sorted(supported)} "
            "or override STANDUP_AGENT_SUPPORTED_MODELS explicitly."
        )
    return model


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _normalize_url(raw: str) -> str:
    return raw.rstrip(TRAILING_URL_PUNCT)


def _infer_service(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if "atlassian" in host and ("/browse/" in path or "jira" in host):
        return "jira"
    if "jira" in host:
        return "jira"
    if "confluence" in host or ("atlassian" in host and "/wiki" in path):
        return "confluence"
    if "github" in host:
        return "github"
    if "snowflake" in host:
        return "snowflake"
    if "servicenow" in host or ".service-now." in host or "snow" in host:
        return "servicenow"
    if "archer" in host:
        return "archer"
    if "mongo" in host:
        return "mongodb"
    return "web"


def _jira_key_from_url(url: str) -> str | None:
    match = JIRA_KEY_RE.search(url.upper())
    return match.group(1) if match else None


def parse_message(raw: dict[str, Any], index: int = 0) -> StandupChatMessage:
    body = str(raw.get("body") or raw.get("text") or raw.get("content") or "")
    msg_id = str(raw.get("id") or raw.get("message_id") or f"msg-{index + 1}")
    links: list[StandupLink] = []
    for match in URL_RE.finditer(body):
        url = _normalize_url(match.group(0))
        links.append(
            StandupLink(
                url=url,
                service=_infer_service(url),
                label=urlparse(url).netloc or url,
                jira_key=_jira_key_from_url(url),
            )
        )
    mentions = _dedupe([m.group(1) for m in MENTION_RE.finditer(body)])
    jira_keys = _dedupe([m.group(1) for m in JIRA_KEY_RE.finditer(body.upper())] + [l.jira_key or "" for l in links])
    return StandupChatMessage(
        id=msg_id,
        author=str(raw.get("author") or raw.get("user") or "unknown"),
        body=body,
        kind=str(raw.get("kind") or "chat"),
        created_at=raw.get("created_at"),
        links=links,
        mentions=mentions,
        jira_keys=jira_keys,
    )


def build_link_context(
    messages: list[dict[str, Any]],
    *,
    selected_issues: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    parsed = [parse_message(m, i) for i, m in enumerate(messages)]
    all_links = [link for msg in parsed for link in msg.links]
    mentions = _dedupe([mention for msg in parsed for mention in msg.mentions])
    jira_keys = _dedupe([key for msg in parsed for key in msg.jira_keys])
    selected_issue_keys = _dedupe(
        [str(issue.get("key") or issue.get("issue_key") or "") for issue in (selected_issues or [])]
    )
    for key in selected_issue_keys:
        if key not in jira_keys:
            jira_keys.append(key)
    return StandupLinkContext(
        messages=parsed,
        links=all_links,
        mentions=mentions,
        jira_keys=jira_keys,
        selected_issue_keys=selected_issue_keys,
    ).model_dump(exclude_none=True)


def _issue_fields(issue: dict[str, Any]) -> dict[str, Any]:
    fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}
    merged = dict(issue)
    merged.update(fields)
    return merged


def _selected_epic_link(selected_issues: list[dict[str, Any]] | None, fallback_keys: list[str] | None = None) -> str | None:
    for issue in selected_issues or []:
        fields = _issue_fields(issue)
        for key in ("epic_key", "customfield_epic_link", "parent", "key", "issue_key"):
            value = fields.get(key)
            if isinstance(value, dict):
                value = value.get("key")
            if value:
                return str(value)
    return (fallback_keys or [None])[0]


def _doc_links(docs_context: list[dict[str, Any]] | None, detected_links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    seen: set[str] = set()
    for doc in docs_context or []:
        url = str(
            doc.get("confluence_url")
            or doc.get("url")
            or doc.get("web_url")
            or doc.get("link")
            or ""
        )
        page_id = doc.get("confluence_page_id") or doc.get("page_id")
        if not url and page_id:
            url = f"confluence://{page_id}"
        slug = str(doc.get("slug") or doc.get("path") or doc.get("id") or url)
        if not slug and not url:
            continue
        identity = url or slug
        if identity in seen:
            continue
        seen.add(identity)
        links.append(
            {
                "title": doc.get("title") or slug,
                "slug": slug,
                "url": url,
                "tags": list(doc.get("tags") or []),
                "visibility": doc.get("visibility"),
                "status": doc.get("status"),
            }
        )
    for link in detected_links:
        if link.get("service") != "confluence":
            continue
        url = str(link.get("url") or "")
        if url and url not in seen:
            seen.add(url)
            links.append({"title": link.get("label") or "Confluence link", "url": url, "service": "confluence"})
    return links


def _template_labels(docs_context: list[dict[str, Any]] | None) -> list[str]:
    labels = list(DEFAULT_STANDUP_LABELS)
    for doc in docs_context or []:
        labels.extend(str(tag) for tag in (doc.get("tags") or []) if tag)
    return _dedupe([label.lower().replace(" ", "-") for label in labels])[:12]


def build_story_template_context(
    link_context: dict[str, Any],
    *,
    selected_issues: list[dict[str, Any]] | None = None,
    docs_context: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return deterministic Jira/story guidance for the LLM and dry-run payloads."""
    epic_link = _selected_epic_link(selected_issues, link_context.get("jira_keys") or [])
    template = render_jira_story(
        {
            "requirement": "Standup follow-up from meeting chat and selected Jira context",
            "regulation": "Standup / compliance workflow",
            "severity": "medium",
        },
        {"jira_key": epic_link or "STANDUP-1"},
    )
    workflow_docs = _doc_links(docs_context, link_context.get("links") or [])
    selected_issue_summaries = []
    for issue in selected_issues or []:
        fields = _issue_fields(issue)
        selected_issue_summaries.append(
            {
                "key": fields.get("key") or issue.get("key") or issue.get("issue_key"),
                "summary": fields.get("summary"),
                "status": (fields.get("status") or {}).get("name") if isinstance(fields.get("status"), dict) else fields.get("status"),
                "priority": (fields.get("priority") or {}).get("name") if isinstance(fields.get("priority"), dict) else fields.get("priority"),
                "epic_key": fields.get("epic_key") or fields.get("customfield_epic_link"),
            }
        )
    return {
        "story_template": template,
        "new_jira_work_payload_contract": {
            "issue_type": "Story/Task/Bug chosen from chat intent",
            "summary": "Action-oriented Jira summary, prefixed with selected epic/key only when helpful",
            "description": "Use the story template structure plus standup context, rationale, and source messages",
            "acceptance_criteria": ACCEPTANCE_CRITERIA_FORMAT,
            "labels": _template_labels(docs_context),
            "priority_guidance": {
                "Critical/Highest": "production outage, active blocker, P1/P2 incident, audit deadline at risk",
                "High": "blocked sprint work, compliance risk, due soon, repeated owner ask",
                "Medium": "normal follow-up or missing association",
                "Low": "nice-to-have cleanup or documentation-only follow-up",
            },
            "story_point_guidance": {"1": "clarification/doc-only", "2-3": "small task", "5": "multi-step investigation", "8": "larger cross-service follow-up"},
            "epic_link": epic_link,
            "doc_links": workflow_docs,
            "related_links": link_context.get("links") or [],
            "dry_run": True,
        },
        "selected_issue_context": selected_issue_summaries,
        "workflow_docs": workflow_docs,
    }


def _coerce_acceptance_criteria(value: Any) -> list[str]:
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
    elif isinstance(value, str) and value.strip():
        items = [line.strip(" -") for line in value.splitlines() if line.strip(" -")]
    else:
        items = []
    return items or list(ACCEPTANCE_CRITERIA_FORMAT)


def _enrich_new_jira_payload(payload: dict[str, Any], proposal: dict[str, Any], template_context: dict[str, Any]) -> dict[str, Any]:
    contract = template_context.get("new_jira_work_payload_contract") or {}
    story_template = template_context.get("story_template") or {}
    enriched = dict(payload)
    enriched.setdefault("dry_run", True)
    enriched.setdefault("issue_type", enriched.get("issuetype") or story_template.get("issuetype", {}).get("name") or "Story")
    enriched.setdefault("summary", enriched.get("title") or proposal.get("title") or story_template.get("summary") or "Standup follow-up")
    enriched.setdefault("description", story_template.get("description") or "Standup follow-up from meeting chat.")
    enriched["acceptance_criteria"] = _coerce_acceptance_criteria(enriched.get("acceptance_criteria"))
    enriched["labels"] = _dedupe([str(label) for label in (enriched.get("labels") or [])] + list(contract.get("labels") or []))
    enriched.setdefault("priority", "Medium")
    try:
        points = float(enriched.get("story_points", 3))
        enriched["story_points"] = int(points) if points.is_integer() else points
    except (TypeError, ValueError):
        enriched["story_points"] = 3
    if contract.get("epic_link") and not enriched.get("epic_link"):
        enriched["epic_link"] = contract["epic_link"]
    if contract.get("doc_links") and not enriched.get("doc_links"):
        enriched["doc_links"] = contract["doc_links"]
    if contract.get("related_links") and not enriched.get("related_links"):
        enriched["related_links"] = contract["related_links"]
    enriched.setdefault("source_message_ids", proposal.get("source_message_ids") or [])
    return enriched


def _empty_result(link_context: dict[str, Any], model: str | None = None) -> dict[str, Any]:
    return {
        "summary": "",
        "decisions": [],
        "risks_blockers": [],
        "follow_ups": [],
        "service_associations": [],
        "proposals": [],
        "link_context": link_context,
        "model": model,
        "dry_run_only": True,
    }


def _normalise_agent_result(
    result: StandupAgentResult,
    link_context: dict[str, Any],
    model: str,
    template_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    template_context = template_context or {}
    proposals: list[dict[str, Any]] = []
    for idx, proposal in enumerate(result.proposals, start=1):
        data = proposal.model_dump(exclude_none=True)
        data["id"] = data.get("id") or f"standup-prop-{uuid.uuid4().hex[:12]}"
        data["status"] = "proposed"
        data["dry_run"] = True
        payload = data.get("dry_run_payload") or {}
        if not isinstance(payload, dict):
            payload = {"value": payload}
        payload.setdefault("dry_run", True)
        if data.get("type") == "new_jira_work":
            payload = _enrich_new_jira_payload(payload, data, template_context)
        data["dry_run_payload"] = payload
        data.setdefault("source_message_ids", [])
        data.setdefault("rationale", "")
        data["order"] = idx
        proposals.append(data)

    payload = result.model_dump(exclude_none=True)
    payload["proposals"] = proposals
    payload["link_context"] = link_context
    payload["story_template_context"] = template_context
    payload["model"] = model
    payload["dry_run_only"] = True
    return payload


async def run_standup_summarize(
    messages: list[dict[str, Any]],
    *,
    selected_issues: list[dict[str, Any]] | None = None,
    docs_context: list[dict[str, Any]] | None = None,
    trigger: str = "manual",
    max_messages: int = 80,
) -> dict[str, Any]:
    """Plan standup follow-ups from chat/context without staging or writing."""
    clipped_messages = messages[-max_messages:] if max_messages > 0 else messages
    link_context = build_link_context(clipped_messages, selected_issues=selected_issues)
    template_context = build_story_template_context(
        link_context,
        selected_issues=selected_issues,
        docs_context=docs_context,
    )
    model = assert_supported_model("planner")
    if not clipped_messages:
        empty = _empty_result(link_context, model=model)
        empty["story_template_context"] = template_context
        return empty

    user_payload = {
        "trigger": trigger,
        "messages": link_context["messages"],
        "selected_issues": selected_issues or [],
        "selected_issue_keys": link_context["selected_issue_keys"],
        "detected_jira_keys": link_context["jira_keys"],
        "detected_links": link_context["links"],
        "docs_context": docs_context or [],
        "story_template_context": template_context,
        "allowed_existing_jira_edit_fields": ["status", "assignee", "priority", "story_points", "summary", "duedate"],
        "required_proposal_state": {"status": "proposed", "dry_run": True},
    }
    out = await structured(
        StandupAgentResult,
        SYSTEM_PROMPT,
        json.dumps(user_payload, indent=2, default=str),
        temperature=0.1,
        role="planner",
    )
    return _normalise_agent_result(out, link_context, model, template_context)


def render_markdown(payload: dict[str, Any]) -> str:
    is_agent_result = "summary" in payload or "proposals" in payload or "link_context" in payload
    lines = ["# Standup agent dry-run" if is_agent_result else "# Standup link context", ""]
    if payload.get("summary"):
        lines.extend([payload["summary"], ""])
    for title, key in [
        ("Decisions", "decisions"),
        ("Risks / blockers", "risks_blockers"),
        ("Follow-ups", "follow_ups"),
        ("Service associations", "service_associations"),
    ]:
        rows = payload.get(key) or []
        if rows:
            lines.append(f"## {title}")
            for row in rows:
                lines.append(f"- {row.get('text', '')}")
            lines.append("")
    proposals = payload.get("proposals") or []
    if is_agent_result:
        lines.append(f"## Proposed dry-run actions ({len(proposals)})")
        if not proposals:
            lines.append("- None")
        for proposal in proposals:
            lines.append(
                f"- **{proposal.get('title', proposal.get('type', 'proposal'))}** "
                f"[{proposal.get('target_service', 'jira')} / {proposal.get('type', 'proposal')}] — "
                f"{proposal.get('rationale', '')}"
            )
    link_context = payload.get("link_context") or payload
    detected = link_context.get("jira_keys") or []
    if detected:
        lines.extend(["", "## Detected Jira keys", ", ".join(detected)])
    links = link_context.get("links") or []
    if links:
        lines.extend(["", "## Detected links"])
        for link in links:
            lines.append(f"- `{link.get('service', 'web')}` {link.get('url', '')}")
    lines.extend(["", "_No external writes were performed; all actions are proposed/dry-run only._"])
    return "\n".join(lines)
