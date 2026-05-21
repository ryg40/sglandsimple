"""Pydantic v2 models for Stage 9 compliance workflow state."""

from __future__ import annotations

from typing import Any
from typing_extensions import TypedDict

from bson import ObjectId
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Entity models (cross-linked by string id)
# ---------------------------------------------------------------------------


class AuditFinding(BaseModel):
    id: str = Field(alias="_id", default_factory=lambda: str(ObjectId()))
    source: str
    regulation: str
    requirement: str
    severity: str  # "low" | "medium" | "high" | "critical"
    status: str  # "open" | "in_progress" | "closed"
    epic_id: str | None = None

    model_config = {"populate_by_name": True, "extra": "allow"}


class Epic(BaseModel):
    id: str = Field(alias="_id", default_factory=lambda: str(ObjectId()))
    jira_key: str
    title: str
    regulation_refs: list[str] = []
    db_platform_combos: list[str] = []
    priority: str  # "low" | "medium" | "high"
    status: str  # "not_started" | "in_progress" | "completed"

    model_config = {"populate_by_name": True, "extra": "allow"}


class WorkItem(BaseModel):
    id: str = Field(alias="_id", default_factory=lambda: str(ObjectId()))
    finding_id: str
    epic_id: str
    jira_key: str | None = None
    type: str = "task"
    status: str = "pending"  # "pending" | "in_progress" | "completed"

    model_config = {"populate_by_name": True, "extra": "allow"}


class PrRecord(BaseModel):
    id: str = Field(alias="_id", default_factory=lambda: str(ObjectId()))
    work_item_id: str
    epic_id: str
    pr_number: int
    branch: str
    status: str  # "open" | "merged" | "closed"
    url: str | None = None

    model_config = {"populate_by_name": True, "extra": "allow"}


class DocRecord(BaseModel):
    id: str = Field(alias="_id", default_factory=lambda: str(ObjectId()))
    epic_id: str
    finding_id: str | None = None
    title: str
    confluence_url: str | None = None
    status: str = "draft"  # "draft" | "published"

    model_config = {"populate_by_name": True, "extra": "allow"}


class LogSample(BaseModel):
    id: str = Field(alias="_id", default_factory=lambda: str(ObjectId()))
    finding_id: str
    epic_id: str | None = None
    source: str
    event_type: str
    message: str
    severity: str  # "info" | "warning" | "error"
    timestamp: str | None = None

    model_config = {"populate_by_name": True, "extra": "allow"}


class WorkflowRun(BaseModel):
    id: str = Field(alias="_id", default_factory=lambda: str(ObjectId()))
    finding_id: str
    epic_id: str
    step_index: int = 0
    status: str = "running"  # "running" | "waiting_approval" | "completed" | "failed"
    artifacts: dict[str, Any] = {}
    dry_run: bool = True
    source: str = "workflow_run"

    model_config = {"populate_by_name": True, "extra": "allow"}


# ---------------------------------------------------------------------------
# LangGraph state shape
# ---------------------------------------------------------------------------


class WorkflowState(TypedDict):
    finding_id: str
    epic_id: str
    step_index: int
    artifacts: dict[str, Any]
    status: str  # "running" | "waiting_approval" | "completed" | "failed"
