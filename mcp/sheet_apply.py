"""sheet_apply: turn a plain-English instruction into a sequence of
audited sheet writes against one of the enterprise collections.

Flow:

    START
      └─ discover_schema   reuses ask_data's catalog
      └─ plan_ops          structured(EditPlan) — list of SheetOp + optional match filter
      └─ expand_matches    if plan included a read filter, run it and expand ids
      └─ apply_ops         sequentially through db.update_one/insert_one/delete_one
    END

Writes go through the same audited write-layer as the spreadsheet UI.
`source="sheet_apply_nl"` distinguishes them in the audit log. The
planner only emits SheetOp variants — there's no free-form Mongo update
shape it can express. A hard cap (`SHEET_APPLY_MAX_OPS`) refuses runs
that would touch more rows than configured.
"""

from __future__ import annotations

import os
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

import db as dbmod
from ask_data import _build_catalog  # reuse the cached catalog builder
from llm import structured

SHEET_APPLY_MAX_OPS = int(os.environ.get("SHEET_APPLY_MAX_OPS", "50"))


# ---------------------------------------------------------------------------
# Op shapes the planner is allowed to emit
# ---------------------------------------------------------------------------


class SetCell(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    op: Literal["set_cell"] = "set_cell"
    id: str = Field(alias="_id")
    field: str
    value: Any | None = None


class InsertRow(BaseModel):
    op: Literal["insert_row"] = "insert_row"
    doc: dict[str, Any]


class DeleteRow(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    op: Literal["delete_row"] = "delete_row"
    id: str = Field(alias="_id")


class MatchFilter(BaseModel):
    """Optional read-side filter the planner can use when the instruction
    references rows by predicate ("everyone in Support hired before 2020").
    The graph executes this as a read-only find(), then expands matched
    _ids into per-row SetCell ops using `set_for_matches`."""

    filter: dict[str, Any]
    set_for_matches: dict[str, Any] = Field(
        default_factory=dict,
        description="{field: value} to $set on every matching row.",
    )


class EditPlan(BaseModel):
    ops: list[SetCell | InsertRow | DeleteRow] = Field(default_factory=list)
    match: MatchFilter | None = None
    rationale: str = ""


# ---------------------------------------------------------------------------
# Result shapes
# ---------------------------------------------------------------------------


class AppliedOp(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    op: str
    id: str | None = Field(default=None, alias="_id")
    field: str | None = None
    before: Any | None = None
    after: Any | None = None


class FailedOp(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    op: str
    id: str | None = Field(default=None, alias="_id")
    field: str | None = None
    error: str


class SheetApplyResult(BaseModel):
    collection: str
    instruction: str
    rationale: str = ""
    applied: list[AppliedOp] = Field(default_factory=list)
    failed: list[FailedOp] = Field(default_factory=list)
    summary: str = ""
    error: str | None = None


# ---------------------------------------------------------------------------
# Planner prompt
# ---------------------------------------------------------------------------


PLAN_SYSTEM = """\
You translate a plain-English edit instruction into an EditPlan — a list
of small ops (set_cell, insert_row, delete_row) that the server will
apply through a strict, audited write-layer.

Rules:
- Pick exactly one collection (the user already told you which).
- Each op refers to a single _id (set_cell, delete_row) or a single new doc (insert_row).
- For set_cell: {"op":"set_cell","_id":"<existing _id>","field":"<top-level field>","value":<new value>}.
- For delete_row: {"op":"delete_row","_id":"<existing _id>"}.
- For insert_row: {"op":"insert_row","doc":{"_id":"<new id>", ...}}.
- If the instruction matches by predicate ("everyone in Support hired before 2020"),
  emit a `match` block with a Mongo filter + a `set_for_matches` map of fields
  to assign on every matched row. The server expands matched _ids into set_cell ops.
- NEVER use $where, $function, $accumulator, $out, or $merge.
- Keep `set_for_matches` to top-level fields only.
- `rationale`: one short sentence explaining the intent.

If the instruction is ambiguous or references a row that isn't in the
schema, return ops=[] and explain in rationale.
"""


# ---------------------------------------------------------------------------
# Graph nodes (called directly — no StateGraph needed for this small flow)
# ---------------------------------------------------------------------------


async def _plan_ops(collection: str, instruction: str, catalog: str) -> EditPlan:
    user = (
        f"Collection: {collection}\n\n"
        f"Catalog:\n{catalog}\n\n"
        f"Instruction: {instruction}"
    )
    return await structured(EditPlan, PLAN_SYSTEM, user, role="planner")


async def _expand_matches(collection: str, match: MatchFilter) -> list[SetCell]:
    spec = {
        "collection": collection,
        "kind": "find",
        "filter": match.filter,
        "limit": SHEET_APPLY_MAX_OPS,
    }
    rows = await dbmod.find(spec)
    expanded: list[SetCell] = []
    for r in rows:
        row_id = r.get("_id")
        if not isinstance(row_id, str):
            continue
        for field, value in match.set_for_matches.items():
            expanded.append(SetCell(id=row_id, field=field, value=value))
    return expanded


def _summarize(result: SheetApplyResult) -> str:
    parts = []
    if result.applied:
        parts.append(f"Applied {len(result.applied)} ops")
    if result.failed:
        parts.append(f"{len(result.failed)} failed")
    if not parts:
        parts.append("No ops applied")
    return "; ".join(parts) + "."


async def run_sheet_apply(collection: str, instruction: str, actor: dict | None = None) -> SheetApplyResult:
    """Plan + apply a natural-language edit instruction."""
    result = SheetApplyResult(collection=collection, instruction=instruction)

    if collection not in dbmod.KNOWN_COLLECTIONS:
        result.error = f"unknown collection: {collection!r}"
        result.summary = result.error
        return result

    if not dbmod.SHEET_WRITES_ENABLED:
        result.error = "writes disabled (SHEET_WRITES_ENABLED=false)"
        result.summary = result.error
        return result

    catalog = await _build_catalog()

    try:
        plan = await _plan_ops(collection, instruction, catalog)
    except Exception as e:  # noqa: BLE001
        result.error = f"planner error: {e}"
        result.summary = result.error
        return result

    result.rationale = plan.rationale

    ops: list[SetCell | InsertRow | DeleteRow] = list(plan.ops)

    if plan.match is not None and plan.match.set_for_matches:
        try:
            expanded = await _expand_matches(collection, plan.match)
        except Exception as e:  # noqa: BLE001
            result.error = f"match expansion failed: {e}"
            result.summary = result.error
            return result
        ops.extend(expanded)

    if len(ops) > SHEET_APPLY_MAX_OPS:
        result.error = (
            f"plan would apply {len(ops)} ops > SHEET_APPLY_MAX_OPS={SHEET_APPLY_MAX_OPS}; refusing"
        )
        result.summary = result.error
        return result

    for op in ops:
        try:
            if isinstance(op, SetCell):
                update_payload = (
                    {"$set": {op.field: op.value}}
                    if op.value is not None
                    else {"$unset": {op.field: ""}}
                )
                info = await dbmod.update_one(
                    collection, op.id, update_payload, source="sheet_apply_nl", actor=actor
                )
                applied = AppliedOp(op="set_cell", id=str(op.id), field=op.field)
                applied.before = (info.get("before") or {}).get(op.field)
                applied.after = (info.get("after") or {}).get(op.field)
                result.applied.append(applied)
            elif isinstance(op, InsertRow):
                info = await dbmod.insert_one(collection, op.doc, source="sheet_apply_nl", actor=actor)
                result.applied.append(
                    AppliedOp(op="insert_row", id=str(info["_id"]), after=info.get("after"))
                )
            elif isinstance(op, DeleteRow):
                info = await dbmod.delete_one(collection, op.id, source="sheet_apply_nl", actor=actor)
                result.applied.append(
                    AppliedOp(op="delete_row", id=str(op.id), before=info.get("before"))
                )
        except Exception as e:  # noqa: BLE001
            result.failed.append(
                FailedOp(
                    op=getattr(op, "op", type(op).__name__),
                    id=getattr(op, "id", None),
                    field=getattr(op, "field", None),
                    error=str(e),
                )
            )

    result.summary = _summarize(result)
    return result


def render_markdown(result: SheetApplyResult) -> str:
    lines = [f"# sheet_apply_nl — {result.collection}", ""]
    lines.append(f"**Instruction:** {result.instruction}")
    if result.rationale:
        lines.append(f"**Rationale:** {result.rationale}")
    lines.append("")
    if result.error:
        lines += [f"**Error:** {result.error}", ""]
    if result.applied:
        lines.append("## Applied")
        for a in result.applied:
            if a.op == "set_cell":
                lines.append(f"- ✓ {a.op} `{a.id}.{a.field}` : `{a.before}` → `{a.after}`")
            elif a.op == "insert_row":
                lines.append(f"- ✓ {a.op} `{a.id}`")
            elif a.op == "delete_row":
                lines.append(f"- ✓ {a.op} `{a.id}`")
        lines.append("")
    if result.failed:
        lines.append("## Failed")
        for f in result.failed:
            lines.append(f"- ✗ {f.op} `{f.id or ''}` — {f.error}")
        lines.append("")
    lines.append(f"_{result.summary}_")
    return "\n".join(lines)
