"""Stage 14 — Confluence reconciliation for the docs wiki.

Pushes `public` wiki docs to Confluence, mirroring the wiki `path` tree as a
Confluence ancestor-page chain. Idempotent: a doc's `confluence_page_id` is
stored after the first create and updated in place thereafter. `tags[]` map to
Confluence labels; `title` → page title; `body_md` → page body.

Safety: this only performs live writes when all three gates are on —
`DOCS_SYNC_ENABLED`, `CONN_CONFLUENCE_ENABLED` (the connector is enabled), and
`WORKFLOW_WRITES_ENABLED` (the audited write-layer is open). Otherwise it
produces the would-create/update plan (dry-run) without any outbound call, and
still records the planned actions to `doc_sync_log`.
"""

from __future__ import annotations

import json
import os
from typing import Any

import db as dbmod
from connectors import get_connector

DOCS_CONFLUENCE_SPACE = os.environ.get("DOCS_CONFLUENCE_SPACE", "COMP")
DOCS_SYNC_ENABLED = os.environ.get("DOCS_SYNC_ENABLED", "false").lower() == "true"


def _live() -> bool:
    """All three gates must be on for outbound writes."""
    conf = get_connector("confluence")
    conn_enabled = bool(conf and getattr(conf, "enabled", False))
    return DOCS_SYNC_ENABLED and conn_enabled and dbmod.WORKFLOW_WRITES_ENABLED


def _ancestor_paths(path: str) -> list[str]:
    """For path "runbooks/rds-audit-logging" → ["runbooks"] (parents only)."""
    segs = [s for s in path.split("/") if s]
    return ["/".join(segs[: i + 1]) for i in range(len(segs) - 1)]


def _parse_envelope_json(result: dict[str, Any]) -> dict[str, Any]:
    for block in reversed(result.get("content", [])):
        if block.get("type") == "text":
            try:
                return json.loads(block["text"])
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
    return {}


async def _confluence_create(title: str, body: str, parent_id: str | None, labels: list[str]) -> dict[str, Any]:
    conf = get_connector("confluence")
    res = await conf.dispatch(
        "confluence_create_page",
        {"title": title, "space": DOCS_CONFLUENCE_SPACE, "body": body, "parent_id": parent_id, "labels": labels},
    )
    return _parse_envelope_json(res)


async def _confluence_update(page_id: str, title: str, body: str, labels: list[str]) -> dict[str, Any]:
    conf = get_connector("confluence")
    res = await conf.dispatch(
        "confluence_update_page",
        {"page_id": page_id, "title": title, "body": body, "labels": labels},
    )
    return _parse_envelope_json(res)


async def _sync_one(doc: dict[str, Any], live: bool, ancestor_ids: dict[str, str]) -> dict[str, Any]:
    slug = doc["slug"]
    path = doc.get("path") or slug
    title = doc.get("title") or slug
    body = doc.get("body_md") or ""
    labels = list(doc.get("tags") or [])
    page_id = doc.get("confluence_page_id")
    parents = _ancestor_paths(path)
    parent_id = ancestor_ids.get(parents[-1]) if parents else None

    if page_id:
        action = "update"
        detail = "would update in place" if not live else "updated"
        if live:
            r = await _confluence_update(page_id, title, body, labels)
            page_id = r.get("id", page_id)
    else:
        action = "create"
        detail = "would create" if not live else "created"
        if live:
            r = await _confluence_create(title, body, parent_id, labels)
            page_id = r.get("id")
            if page_id:
                await dbmod.docs_set_confluence_id(slug, page_id)

    entry = {
        "doc_id": doc["_id"],
        "slug": slug,
        "direction": "push",
        "confluence_page_id": page_id,
        "action": action if live else "skip",
        "planned_action": action,
        "space": DOCS_CONFLUENCE_SPACE,
        "path": path,
        "parent_id": parent_id,
        "labels": labels,
        "live": live,
        "detail": detail,
    }
    await dbmod.doc_sync_log_append(entry)
    return entry


async def run_docs_sync(*, slug: str | None = None) -> dict[str, Any]:
    """Reconcile public docs → Confluence. Returns a plan/result payload."""
    live = _live()
    if slug:
        one = await dbmod.docs_get(slug)
        docs = [one] if one and one.get("visibility") == "public" else []
    else:
        docs = await dbmod.docs_list(visibility="public", include_archived=False)
        # docs_list omits bodies; reload full docs for sync.
        full = []
        for d in docs:
            fd = await dbmod.docs_get(d["slug"])
            if fd:
                full.append(fd)
        docs = full

    # Build the ancestor-page map first (intermediate pages mirror the tree).
    ancestor_ids: dict[str, str] = {}
    needed_parents: set[str] = set()
    for d in docs:
        for p in _ancestor_paths(d.get("path") or d["slug"]):
            needed_parents.add(p)
    for p in sorted(needed_parents, key=lambda x: x.count("/")):
        title = p.split("/")[-1].replace("-", " ").title()
        if live:
            r = await _confluence_create(title, f"# {title}\n\n_Section index._", None, [])
            ancestor_ids[p] = r.get("id", f"section-{p}")
        else:
            ancestor_ids[p] = f"section-{p}"  # planned id, dry-run

    actions = [await _sync_one(d, live, ancestor_ids) for d in docs]
    return {
        "live": live,
        "space": DOCS_CONFLUENCE_SPACE,
        "considered": len(docs),
        "ancestors": ancestor_ids,
        "actions": actions,
    }
