"""Pydantic models for the ask_data LangGraph workflow.

Split out from `ask_data.py` so nodes and the MCP server layer can import
them without circular dependencies.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


class QuerySpec(BaseModel):
    """Planner-emitted Mongo query plan. Validated by db.validate_spec."""

    collection: Literal["employees", "tickets", "documents"]
    kind: Literal["find", "aggregate"]
    filter: dict[str, Any] | None = None
    projection: dict[str, Any] | None = None
    sort: dict[str, Any] | None = None
    limit: int = Field(default=20, ge=1, le=50)
    pipeline: list[dict[str, Any]] | None = None
    rationale: str


class DocNote(BaseModel):
    doc_id: str
    note: str


class Evidence(BaseModel):
    index: int
    doc_id: str
    collection: str = ""
    quote: str
    why: str


class FinalAnswer(BaseModel):
    answer: str
    evidence: list[Evidence]
    # NOTE: query_used is filled in by the synthesize node from the actual
    # spec we ran, so the model can omit it. It's kept on the response as a
    # convenience for callers, not as a real input field.
    query_used: QuerySpec | None = None


class AskDataState(BaseModel):
    question: str
    catalog: str | None = None
    spec: QuerySpec | None = None
    spec_error: str | None = None
    retry_count: int = 0
    docs: list[dict[str, Any]] = Field(default_factory=list)
    per_doc_notes: Annotated[list[DocNote], operator.add] = Field(default_factory=list)
    final: FinalAnswer | None = None
