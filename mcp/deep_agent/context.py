"""Deep Agent platform — context packs (Stage 21, S21.context.1).

A *context pack* is a compact, versioned bundle of templates / schemas /
examples / runbook links that one agent needs, requested by name in a profile's
``context_packs``. Packs keep each subagent's prompt small (the reason the
platform delegates at all): an agent loads only its own packs, never the whole
corpus.

Packs are sourced from **existing material** — they don't invent new prompts:

- ``jira_story_template`` / ``standup_labels`` reuse the Stage-20 standup
  agent's deterministic story-template context (``mcp/standup_agent.py``).

**Stage-24 convergence:** when the Stage-24 ``standup_templates`` store exists
(``S24.templates.api.1``), the Jira/Confluence prompt packs should read their
bodies from it — the single source of truth shared with the standup Templates
panel — rather than this module duplicating them. ``_load_standup_templates``
is the seam: it tries that store first and falls back to the in-repo material,
so neither side forks. See ``docs/deep_agent_platform.md`` §6.
"""

from __future__ import annotations

from typing import Callable

# Reuse the standup agent's existing, tested template material rather than
# re-deriving it. Import lazily inside builders so this module stays
# import-light and usable in tests without the full standup stack.


class ContextPack:
    """A named, versioned bundle rendered into a compact prompt block."""

    def __init__(self, name: str, version: str, builder: Callable[[], str]):
        self.name = name
        self.version = version
        self._builder = builder

    def render(self) -> str:
        body = self._builder()
        return f"<!-- context pack: {self.name} v{self.version} -->\n{body}"


def _try_standup_templates_store() -> list[dict] | None:
    """Stage-24 convergence seam.

    Returns the shared ``standup_templates`` records if that store exists, else
    ``None`` so callers fall back to the in-repo material. Built defensively:
    Stage 24 is not yet implemented, so a missing module/tool is expected and
    must not raise.
    """
    try:  # pragma: no cover - exercised once Stage 24 lands
        import standup_templates  # type: ignore

        loader = getattr(standup_templates, "list_templates", None)
        if callable(loader):
            return list(loader())
    except Exception:
        return None
    return None


def _build_jira_story_template() -> str:
    from standup_agent import (
        ACCEPTANCE_CRITERIA_FORMAT,
        build_story_template_context,
    )

    # Prefer the shared Stage-24 store when present (single source of truth).
    store = _try_standup_templates_store()
    if store:
        jira = [t for t in store if t.get("kind") == "jira"]
        if jira:
            lines = ["Jira ticket templates (from the shared standup_templates store):"]
            for t in jira:
                lines.append(f"\n## {t.get('name')}\n{t.get('body_md', '').strip()}")
            return "\n".join(lines)

    ctx = build_story_template_context({"jira_keys": [], "links": []})
    contract = ctx.get("new_jira_work_payload_contract", {})
    parts = [
        "Jira story shape for new follow-up tickets:",
        f"- issue type: {contract.get('issue_type', 'Story')}",
        f"- summary: {contract.get('summary', '(short imperative title)')}",
        "- acceptance criteria format:",
        *[f"  - {c}" for c in ACCEPTANCE_CRITERIA_FORMAT],
        f"- priority guidance: {contract.get('priority_guidance', {})}",
        f"- story-point guidance: {contract.get('story_point_guidance', {})}",
    ]
    return "\n".join(parts)


def _build_standup_labels() -> str:
    from standup_agent import DEFAULT_STANDUP_LABELS

    return "Default labels for agent-proposed work: " + ", ".join(DEFAULT_STANDUP_LABELS)


_PACKS: dict[str, ContextPack] = {
    "jira_story_template": ContextPack("jira_story_template", "1", _build_jira_story_template),
    "standup_labels": ContextPack("standup_labels", "1", _build_standup_labels),
}


def available_packs() -> list[str]:
    return sorted(_PACKS)


def render_packs(names: list[str]) -> str:
    """Render the named packs into one compact block for a subagent prompt.

    Unknown pack names raise — a profile referencing a missing pack is a config
    error we want surfaced at startup (consistent with profile fail-fast).
    """
    missing = [n for n in names if n not in _PACKS]
    if missing:
        raise ValueError(f"unknown context pack(s): {sorted(missing)}")
    if not names:
        return ""
    return "\n\n".join(_PACKS[n].render() for n in names)


def validate_profile_packs(pack_names_by_agent: dict[str, list[str]]) -> list[str]:
    """Return errors for any agent referencing an unknown context pack."""
    errors: list[str] = []
    for agent, packs in pack_names_by_agent.items():
        unknown = [p for p in packs if p not in _PACKS]
        if unknown:
            errors.append(f"agent {agent!r}: unknown context pack(s) {sorted(unknown)}")
    return errors
