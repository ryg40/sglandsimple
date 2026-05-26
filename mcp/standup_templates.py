"""Shared Standup prompt/template store (Stage 24).

This module is deliberately plain data + pure helpers. It is the single source
of truth for the Stage-24 Templates panel and for Stage-21 Deep Agent context
packs that need Jira/Confluence generation prompts. Keeping it decoupled from a
specific agent runtime lets the hand-rolled Stage-4 deep-agent and the
LangChain/deepagents runtime consume the same template bodies.
"""

from __future__ import annotations

import copy
import os
from typing import Any

TEMPLATE_STORE_VERSION = "1"

_TEMPLATES: list[dict[str, Any]] = [
    {
        "name": "Jira follow-up story",
        "kind": "jira",
        "description": "Draft a compliance-oriented Jira story from standup notes and selected epic context.",
        "body_md": """# Jira follow-up story prompt\n\nUse this template when standup chat implies new Jira work. Generate a **draft only**; do not call a write tool.\n\n## Inputs\n\n- Standup summary and source message IDs\n- Selected epic key / Jira issue context\n- Relevant links (Confluence, GitHub, ServiceNow, Archer, Snowflake, Mongo evidence)\n- Program area, regulation refs, database/platform combos, labels\n\n## Output fields\n\nReturn a Jira story payload with:\n\n- `summary`: short imperative title\n- `description`: context, scope, related evidence, and owner handoff notes\n- `issue_type`: `Story` unless the context clearly says task or bug\n- `labels`: include `standup-follow-up`, `dry-run`, and domain labels\n- `priority`: infer conservatively from blocker/risk language\n- `story_points`: small integer estimate or `null` when unclear\n- `acceptance_criteria`: Given/When/Then bullets tied to evidence and review\n- `epic_link`: selected epic key when known\n- `related_links` / `doc_links`: source links with service labels\n- `source_message_ids`: all chat messages that justify the proposal\n\n## Safety\n\nKeep `dry_run=true` and `status=proposed`. If the standup note is ambiguous, state the missing context and lower confidence instead of inventing details.\n""",
    },
    {
        "name": "Jira existing-issue edit",
        "kind": "jira",
        "description": "Draft a safe existing Jira issue edit from explicit standup direction.",
        "body_md": """# Jira existing-issue edit prompt\n\nUse this template when a participant explicitly asks to update an existing Jira issue.\n\n## Allowed edit fields\n\nOnly propose changes to:\n\n- `summary`\n- `status`\n- `assignee`\n- `priority`\n- `story_points`\n- `duedate`\n\n## Required evidence\n\n- Existing `issue_key` from chat, pasted link, or selected Explorer row\n- Rationale explaining why the field change is warranted\n- Source message IDs\n\n## Output\n\nReturn `{ issue_key, changes, rationale, source_message_ids, dry_run: true }`. The Standup websocket path will stage and validate edits through the existing Jira staging tools before any approver sees them.\n""",
    },
    {
        "name": "Confluence evidence note",
        "kind": "confluence",
        "description": "Draft an evidence/runbook note linked to Jira and audit findings.",
        "body_md": """# Confluence evidence note prompt\n\nUse this template to draft a Confluence page or section update from standup outcomes. Generate a Markdown draft only; live Confluence updates require HITL and connector write gates.\n\n## Structure\n\n1. **Decision / outcome** — what the team agreed to.\n2. **Scope** — affected epic, findings, services, database platforms, and environments.\n3. **Evidence links** — Jira tickets, PRs, ServiceNow changes, Snowflake/Mongo evidence, screenshots or logs.\n4. **Open questions** — items that still need owner confirmation.\n5. **Next review** — who should review and when.\n\n## Safety\n\nPreserve exact identifiers (`finding_id`, `epic_key`, ticket refs, PR numbers, change IDs). Do not claim evidence exists unless it is present in the supplied links or retrieved context.\n""",
    },
]


def templates_enabled() -> bool:
    """Whether the public MCP/UI read surface should expose templates."""
    return os.environ.get("STANDUP_TEMPLATES_ENABLED", "true").lower() == "true"


def list_templates() -> list[dict[str, Any]]:
    """Return template records for UI previews and agent context packs.

    Future Stage-24+ editability should replace or augment this in-memory list
    with an audited store/upsert path, while keeping this function as the read
    seam consumed by both the UI and Deep Agent context packs.
    """
    return copy.deepcopy(_TEMPLATES)


def payload() -> dict[str, Any]:
    return {
        "enabled": templates_enabled(),
        "version": TEMPLATE_STORE_VERSION,
        "templates": list_templates() if templates_enabled() else [],
    }


def render_markdown(data: dict[str, Any] | None = None) -> str:
    data = data or payload()
    if not data.get("enabled"):
        return "# Standup templates\n\nTemplates panel is disabled by `STANDUP_TEMPLATES_ENABLED=false`."
    lines = ["# Standup templates", "", f"Version: `{data.get('version', TEMPLATE_STORE_VERSION)}`", ""]
    for item in data.get("templates", []):
        lines.append(f"## {item.get('name')} ({item.get('kind')})")
        if item.get("description"):
            lines.append(str(item["description"]))
        lines.append("")
    return "\n".join(lines).strip()
