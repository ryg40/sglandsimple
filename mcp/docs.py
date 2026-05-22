"""Stage 14 — Docs Wiki CRUD + search + lifecycle over the `docs` collection.

Thin tool layer on top of the docs system-of-record helpers in db.py. Every
write routes through the Stage-6 audited write-layer (source="docs_*") and
appends to `doc_revisions` on content change. Markdown is stored verbatim and
rendered client-side; this module never calls the LLM.

The lifecycle rules in 14b are computed here on read so the UI and the agent
triage agree on what counts as `needs_attention` / `archivable`:

  - needs_attention  ← now - last_reviewed_at > DOCS_REVIEW_DAYS
  - archivable       ← stale AND unreferenced (no other doc links to it)
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import db as dbmod

DOCS_REVIEW_DAYS = int(os.environ.get("DOCS_REVIEW_DAYS", "90"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _stale(doc: dict[str, Any], ref: datetime) -> bool:
    reviewed = _parse_dt(doc.get("last_reviewed_at")) or _parse_dt(doc.get("updated_at"))
    if reviewed is None:
        return True
    return (ref - reviewed).total_seconds() / 86400.0 > DOCS_REVIEW_DAYS


def _referenced_slugs(docs: list[dict[str, Any]]) -> set[str]:
    """Slugs that some other doc's body links to (markdown link to /docs/<slug>
    or a bare path mention). Used to decide `archivable` (stale AND unreferenced)."""
    refs: set[str] = set()
    paths = {d.get("path") or d.get("slug"): d.get("slug") for d in docs}
    # bodies are omitted from list payloads, so this is computed in the triage
    # path where full bodies are loaded; for list views we approximate with the
    # stored status only.
    for d in docs:
        body = d.get("body_md") or ""
        for path, slug in paths.items():
            if path and slug and path in body:
                refs.add(slug)
    return refs


def derive_status(doc: dict[str, Any], *, ref: datetime | None = None, referenced: set[str] | None = None) -> str:
    """Compute the lifecycle status the UI should show, honoring manual archive.

    Manual `archived` always wins. Otherwise: stale+unreferenced → archivable;
    stale → needs_attention; else keep the stored status (default up_to_date).
    """
    ref = ref or _now()
    stored = doc.get("status") or "up_to_date"
    if stored == "archived":
        return "archived"
    stale = _stale(doc, ref)
    if not stale:
        return stored if stored in ("needs_attention",) else stored or "up_to_date"
    slug = doc.get("slug")
    if referenced is not None and slug not in referenced:
        return "archivable"
    return "needs_attention"


def _tree(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group docs by their leading path segment into a one-level nav tree.

    [{group: "runbooks", docs: [...]}, {group: "(root)", docs: [...]}]
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for d in docs:
        path = d.get("path") or d.get("slug") or ""
        seg = path.split("/")[0] if "/" in path else "(root)"
        groups.setdefault(seg, []).append(d)
    out = [{"group": g, "docs": sorted(items, key=lambda x: x.get("path", ""))} for g, items in groups.items()]
    out.sort(key=lambda x: (x["group"] == "(root)", x["group"]))
    return out


async def build_tree(
    *, tag: str | None = None, status: str | None = None, visibility: str | None = None, include_archived: bool = False
) -> dict[str, Any]:
    docs = await dbmod.docs_list(
        tag=tag, status=status, visibility=visibility, include_archived=include_archived
    )
    ref = _now()
    for d in docs:
        d["derived_status"] = derive_status(d, ref=ref)
    review_queue = [
        {"slug": d["slug"], "title": d.get("title"), "status": d["derived_status"], "path": d.get("path")}
        for d in docs
        if d["derived_status"] in ("needs_attention", "archivable")
    ]
    return {
        "tree": _tree(docs),
        "docs": docs,
        "review_queue": review_queue,
        "count": len(docs),
        "review_days": DOCS_REVIEW_DAYS,
        "generated_at": ref.isoformat(),
    }


async def get_doc(slug: str) -> dict[str, Any] | None:
    doc = await dbmod.docs_get(slug)
    if doc is None:
        return None
    doc["derived_status"] = derive_status(doc)
    doc["revisions"] = await dbmod.docs_revisions(doc["_id"])
    doc["sync_log"] = await dbmod.doc_sync_log_recent(doc_id=doc["_id"], limit=10)
    return doc
