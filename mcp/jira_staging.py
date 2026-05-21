"""Stage 16 — HIL-gated staging store for bulk Jira edits.

Edits made in the web grid are *staged* here (Mongo `jira_staged_changes`)
rather than written straight to Jira. The lifecycle is strictly:

    stage  ->  validate  ->  apply

and nothing reaches the live Jira API until `apply` runs **and**
`JIRA_WRITES_ENABLED=true`. With writes disabled (the default) `apply`
produces an auditable dry-run plan and mutates nothing external.

Every mutation (stage / validate / revert / apply) appends an `audit_log`
row via the shared `db._audit` helper, tagged `source="jira_<action>"`.

The current Jira state is owned by the connector (its `_SAMPLE`, or a live
search later); callers pass it in as `current_issues` so this module never
imports the connector and the source of truth stays in one place.
"""

from __future__ import annotations

import datetime as _dt
import os
from typing import Any, Iterable

import db as dbmod

STAGE_COLLECTION = "jira_staged_changes"

JIRA_WRITES_ENABLED = os.environ.get("JIRA_WRITES_ENABLED", "false").lower() == "true"
JIRA_STAGE_MAX_EDITS = int(os.environ.get("JIRA_STAGE_MAX_EDITS", "100"))

# Fields a human is allowed to bulk-edit. Enforced server-side at both stage
# and validate time; the frontend allowlist is convenience only.
EDITABLE_FIELDS = ("status", "assignee", "priority", "story_points", "summary", "duedate")

# Validation enums.
ALLOWED_STATUS = ("To Do", "In Progress", "Blocked", "In Review", "Done", "Deferred")
ALLOWED_PRIORITY = ("Lowest", "Low", "Medium", "High", "Highest", "Critical")


def _stage_id(issue_key: str) -> str:
    return f"jira-stage-{issue_key}"


def _current_field(issue: dict[str, Any], field: str) -> Any:
    """Read a field's current value off the connector's denormalized issue."""
    if field in issue:
        return issue.get(field)
    # fall back to the Jira REST `fields.*` shape
    f = issue.get("fields") or {}
    if field == "status":
        return (f.get("status") or {}).get("name")
    if field == "priority":
        return (f.get("priority") or {}).get("name")
    if field == "assignee":
        return (f.get("assignee") or {}).get("displayName")
    if field == "story_points":
        return f.get("customfield_story_points")
    return f.get(field)


def _index_issues(current_issues: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {i["key"]: i for i in current_issues if i.get("key")}


# ---------------------------------------------------------------------------
# list / merge
# ---------------------------------------------------------------------------


async def list_issues(current_issues: list[dict[str, Any]]) -> dict[str, Any]:
    """Return current issues overlaid with any staged edits.

    Each row gains `_staged` (field -> proposed value), `_stage_status`,
    and `_validation` so the grid can render pending state + badges.
    """
    db = dbmod.get_db()
    staged: dict[str, dict[str, Any]] = {}
    async for doc in db[STAGE_COLLECTION].find({}):
        staged[doc["issue_key"]] = doc

    rows: list[dict[str, Any]] = []
    for issue in current_issues:
        row = dict(issue)
        s = staged.get(issue.get("key"))
        if s and s.get("status") != "reverted":
            row["_staged"] = {f: c["to"] for f, c in (s.get("changes") or {}).items()}
            row["_stage_status"] = s.get("status")
            row["_validation"] = s.get("validation")
        else:
            row["_staged"] = {}
            row["_stage_status"] = None
            row["_validation"] = None
        rows.append(row)
    return {"issues": rows, "staged_count": sum(1 for s in staged.values() if s.get("status") != "reverted")}


# ---------------------------------------------------------------------------
# stage
# ---------------------------------------------------------------------------


async def stage_edits(
    edits: list[dict[str, Any]],
    current_issues: list[dict[str, Any]],
    *,
    staged_by: str = "web",
) -> dict[str, Any]:
    """Persist proposed field changes as staged diffs. Bulk.

    `edits` is a list of `{issue_key, changes: {field: value}}`. Computes a
    `{from, to}` diff against current Jira state; resets status to "staged".
    """
    if len(edits) > JIRA_STAGE_MAX_EDITS:
        raise dbmod.SpecError(
            f"staging {len(edits)} edits exceeds JIRA_STAGE_MAX_EDITS={JIRA_STAGE_MAX_EDITS}"
        )

    index = _index_issues(current_issues)
    db = dbmod.get_db()
    staged_keys: list[str] = []
    rejected: list[dict[str, str]] = []

    for edit in edits:
        key = edit.get("issue_key")
        if not key or key not in index:
            rejected.append({"issue_key": str(key), "reason": "unknown issue_key"})
            continue
        bad = [f for f in (edit.get("changes") or {}) if f not in EDITABLE_FIELDS]
        if bad:
            rejected.append({"issue_key": key, "reason": f"non-editable fields: {', '.join(bad)}"})
            continue

        issue = index[key]
        changes: dict[str, dict[str, Any]] = {}
        for field, to in (edit.get("changes") or {}).items():
            frm = _current_field(issue, field)
            if frm == to:
                continue  # no-op edit, skip
            changes[field] = {"from": frm, "to": to}

        sid = _stage_id(key)
        before = await db[STAGE_COLLECTION].find_one({"_id": sid})
        if not changes:
            # editing back to original clears the staged doc
            await db[STAGE_COLLECTION].delete_one({"_id": sid})
            await dbmod._audit("jira_unstage", STAGE_COLLECTION, sid, before, None, "jira_stage")
            continue

        doc = {
            "_id": sid,
            "issue_key": key,
            "changes": changes,
            "status": "staged",
            "validation": None,
            "staged_by": staged_by,
            "staged_at": _dt.datetime.utcnow(),
        }
        await db[STAGE_COLLECTION].replace_one({"_id": sid}, doc, upsert=True)
        await dbmod._audit("jira_stage", STAGE_COLLECTION, sid, before, doc, "jira_stage")
        staged_keys.append(key)

    return {"staged": staged_keys, "rejected": rejected, "writes_enabled": JIRA_WRITES_ENABLED}


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


def _validate_change(field: str, value: Any) -> str | None:
    """Return an error message for an invalid value, or None if OK."""
    if field == "status" and value not in ALLOWED_STATUS:
        return f"status must be one of {', '.join(ALLOWED_STATUS)}"
    if field == "priority" and value not in ALLOWED_PRIORITY:
        return f"priority must be one of {', '.join(ALLOWED_PRIORITY)}"
    if field == "story_points":
        try:
            if float(value) < 0:
                return "story_points must be non-negative"
        except (TypeError, ValueError):
            return "story_points must be a number"
    if field == "summary" and (value is None or str(value).strip() == ""):
        return "summary must not be empty"
    if field == "duedate" and value not in (None, ""):
        try:
            _dt.date.fromisoformat(str(value)[:10])
        except ValueError:
            return "duedate must be an ISO date (YYYY-MM-DD)"
    if field == "assignee" and (value is None or str(value).strip() == ""):
        return "assignee must not be empty"
    return None


async def validate_staged(issue_keys: list[str] | None = None) -> dict[str, Any]:
    """Run validation rules over staged docs, marking each validated/invalid."""
    db = dbmod.get_db()
    query: dict[str, Any] = {"status": {"$in": ["staged", "validated", "invalid"]}}
    if issue_keys:
        query["issue_key"] = {"$in": issue_keys}

    results: list[dict[str, Any]] = []
    async for doc in db[STAGE_COLLECTION].find(query):
        errors: list[dict[str, str]] = []
        for field, change in (doc.get("changes") or {}).items():
            if field not in EDITABLE_FIELDS:
                errors.append({"field": field, "message": "field is not editable"})
                continue
            msg = _validate_change(field, change.get("to"))
            if msg:
                errors.append({"field": field, "message": msg})

        ok = not errors
        validation = {"ok": ok, "errors": errors}
        new_status = "validated" if ok else "invalid"
        before = dict(doc)
        await db[STAGE_COLLECTION].update_one(
            {"_id": doc["_id"]},
            {"$set": {"status": new_status, "validation": validation, "validated_at": _dt.datetime.utcnow()}},
        )
        await dbmod._audit(
            "jira_validate", STAGE_COLLECTION, doc["_id"], before.get("validation"), validation, "jira_validate"
        )
        results.append({"issue_key": doc["issue_key"], "status": new_status, "validation": validation})

    return {"results": results, "validated": sum(1 for r in results if r["status"] == "validated")}


# ---------------------------------------------------------------------------
# revert
# ---------------------------------------------------------------------------


async def revert_staged(issue_keys: list[str] | None = None) -> dict[str, Any]:
    """Delete staged docs (all if no keys) so the grid returns to live state."""
    db = dbmod.get_db()
    query: dict[str, Any] = {}
    if issue_keys:
        query["issue_key"] = {"$in": issue_keys}

    reverted: list[str] = []
    async for doc in db[STAGE_COLLECTION].find(query):
        await db[STAGE_COLLECTION].delete_one({"_id": doc["_id"]})
        await dbmod._audit("jira_revert", STAGE_COLLECTION, doc["_id"], doc, None, "jira_revert")
        reverted.append(doc["issue_key"])
    return {"reverted": reverted}


# ---------------------------------------------------------------------------
# apply (HIL-gated)
# ---------------------------------------------------------------------------


async def apply_staged(
    issue_keys: list[str] | None,
    *,
    live_writer=None,
) -> dict[str, Any]:
    """Apply **validated** staged changes.

    With `JIRA_WRITES_ENABLED=false` (default) this builds a dry-run plan of
    the `jira_update_issue` calls it *would* make and mutates nothing
    external. With writes enabled and a `live_writer` coroutine supplied, it
    invokes that per issue. Refuses any row not in `validated` state.
    """
    db = dbmod.get_db()
    query: dict[str, Any] = {"status": {"$in": ["validated", "staged", "invalid"]}}
    if issue_keys:
        query["issue_key"] = {"$in": issue_keys}

    mode = "live" if JIRA_WRITES_ENABLED else "dry_run"
    plan: list[dict[str, Any]] = []
    applied: list[str] = []
    skipped: list[dict[str, str]] = []

    async for doc in db[STAGE_COLLECTION].find(query):
        if doc.get("status") != "validated":
            skipped.append({"issue_key": doc["issue_key"], "reason": f"not validated (status={doc.get('status')})"})
            continue

        fields = {f: c["to"] for f, c in (doc.get("changes") or {}).items()}
        call = {"tool": "jira_update_issue", "issue_key": doc["issue_key"], "fields": fields}
        plan.append(call)

        if mode == "live":
            if live_writer is None:
                skipped.append({"issue_key": doc["issue_key"], "reason": "no live writer available"})
                continue
            await live_writer(doc["issue_key"], fields)

        before = dict(doc)
        await db[STAGE_COLLECTION].update_one(
            {"_id": doc["_id"]},
            {"$set": {"status": "applied", "apply_mode": mode, "applied_at": _dt.datetime.utcnow()}},
        )
        await dbmod._audit(
            "jira_apply", STAGE_COLLECTION, doc["_id"], before, {"fields": fields, "apply_mode": mode}, "jira_apply"
        )
        applied.append(doc["issue_key"])

    return {
        "apply_mode": mode,
        "writes_enabled": JIRA_WRITES_ENABLED,
        "applied": applied,
        "skipped": skipped,
        "plan": plan,
        "note": (
            "Dry-run: no changes were sent to Jira. Set JIRA_WRITES_ENABLED=true to apply for real."
            if mode == "dry_run"
            else "Applied to live Jira."
        ),
    }
