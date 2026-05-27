"""MCP server exposing summarize_text, chat, echo, web_research, and the
stage-1 mongo/ask_data tools.

Implements the subset of the Model Context Protocol needed for tools:
- initialize / initialized
- tools/list
- tools/call

Transport is JSON-RPC 2.0 over HTTP POST at /mcp. GET /mcp returns a
per-session SSE stream with keepalives and JSON-RPC response events for
clients that keep a Streamable-HTTP receive stream open.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

import db as dbmod
import sandbox as sbx
import wrangler as wranglermod
from ask_data import render_markdown as render_ask_data_markdown
from ask_data import run_ask_data
from connectors import connector_tools, get_connector, init_connectors, list_connectors
from deep_agent import Plan, run_deep_agent, run_plan_task, run_run_plan
from workflow.graph import run_compliance_workflow
from identity_enrichment import build_identity_enrichment, render_markdown as render_identity_enrichment_markdown
from report.pdf import generate_pdf_report
from report.ppt import generate_ppt_report
from topology import build_topology
from architecture import build_architecture
from overview import build_overview
import docs as docsmod
import standup_agent as standupmod
import standup_intake as standupintakemod
import standup_templates as standuptemplatesmod
from web_research import render_markdown as render_web_research_markdown
from web_research import run_web_research


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} environment variable is required")
    return value


UPSTREAM_BASE_URL = _required_env("UPSTREAM_BASE_URL")
UPSTREAM_API_KEY = os.environ.get("UPSTREAM_API_KEY", "dummy")
UPSTREAM_MODEL = _required_env("UPSTREAM_MODEL")
REQUEST_TIMEOUT = float(os.environ.get("UPSTREAM_TIMEOUT", "120"))

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "sglandsimple-mcp", "version": "0.2.0"}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "summarize_text",
        "description": "Summarize the user-provided text into a short paragraph capturing the key points.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The text to summarize."},
                "max_words": {
                    "type": "integer",
                    "description": "Soft cap on summary length in words.",
                    "default": 80,
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "chat",
        "description": "Engage in a multi-turn conversation. Pass the running message history; receive the assistant's next reply.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "messages": {
                    "type": "array",
                    "description": "OpenAI-style messages, each {role, content}.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "role": {"type": "string", "enum": ["system", "user", "assistant"]},
                            "content": {"type": "string"},
                        },
                        "required": ["role", "content"],
                    },
                },
                "system": {
                    "type": "string",
                    "description": "Optional system prompt prepended to the conversation.",
                },
            },
            "required": ["messages"],
        },
    },
    {
        "name": "echo",
        "description": "Diagnostic: return the input verbatim. Useful for confirming MCP wiring.",
        "inputSchema": {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
    },
    {
        "name": "web_research",
        "description": (
            "Research a topic on the web. Searches SearXNG for relevant results, "
            "annotates each in parallel, then produces a constrained-JSON synthesis "
            "with citations and a verbatim quote from the best result. Returns both "
            "Markdown and JSON renderings."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "The topic or question to research."},
                "k": {
                    "type": "integer",
                    "description": "Number of search results to consider (minimum 5).",
                    "default": 5,
                    "minimum": 5,
                },
            },
            "required": ["topic"],
        },
    },
    {
        "name": "mongo_list_collections",
        "description": "List the enterprise Mongo collections available to the agent, with document counts.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "mongo_describe_collection",
        "description": "Return a sampled schema for one of the enterprise collections.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Collection name. One of: employees, tickets, documents.",
                },
                "sample": {
                    "type": "integer",
                    "description": "Number of documents to sample for the schema (default 5).",
                    "default": 5,
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "mongo_query",
        "description": (
            "Run a validated, read-only Mongo find() against one of the enterprise "
            "collections. The spec is rejected if it contains $where, $function, "
            "$accumulator, $out, or $merge. Limit is clamped to the server ceiling."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "collection": {"type": "string", "enum": ["employees", "tickets", "documents"]},
                "filter": {"type": "object", "default": {}},
                "projection": {"type": "object"},
                "sort": {"type": "object"},
                "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 50},
                "skip": {"type": "integer", "minimum": 0},
            },
            "required": ["collection"],
        },
    },
    {
        "name": "mongo_aggregate",
        "description": (
            "Run a validated, read-only Mongo aggregate() against one of the enterprise "
            "collections. Stages containing $out, $merge, $function, $accumulator, or $where "
            "are rejected. Result size is clamped to the server ceiling."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "collection": {"type": "string", "enum": ["employees", "tickets", "documents"]},
                "pipeline": {"type": "array", "items": {"type": "object"}},
                "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 50},
            },
            "required": ["collection", "pipeline"],
        },
    },
    {
        "name": "ask_data",
        "description": (
            "Answer a natural-language question about the enterprise data by planning "
            "a Mongo query, executing it, and synthesising a cited answer. Returns "
            "markdown plus the structured JSON result."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The question to answer."},
            },
            "required": ["question"],
        },
    },
    {
        "name": "fs_read",
        "description": "Read a UTF-8 file from the sandbox (/sandbox). Paths must be relative; traversal is rejected.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to /sandbox."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "fs_write",
        "description": "Write/replace a UTF-8 file in the sandbox. Creates parent directories as needed.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to /sandbox."},
                "content": {"type": "string", "description": "Full file contents."},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "fs_edit",
        "description": "Exact-string replace in a sandbox file. old_string must be unique within the file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_string": {"type": "string"},
                "new_string": {"type": "string"},
            },
            "required": ["path", "old_string", "new_string"],
        },
    },
    {
        "name": "shell_exec",
        "description": (
            "Run a bash command inside /sandbox as the non-root sandbox user. "
            "stdout/stderr are returned along with the exit code. Times out after "
            "timeout_sec seconds (default 30)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "cmd": {"type": "string", "description": "Command line passed to `bash -lc`."},
                "timeout_sec": {"type": "number", "description": "Hard timeout in seconds.", "default": 30},
            },
            "required": ["cmd"],
        },
    },
    {
        "name": "plan_task",
        "description": (
            "Planner subagent. Decomposes a goal into a typed Plan of MCP tool "
            "calls (with depends_on and parallel flags). Persists the plan to "
            "db.deep_agent_plans and returns it. Does not execute."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "goal": {"type": "string", "description": "The user goal to plan for."},
                "context": {"type": "string", "description": "Optional extra context.", "default": ""},
            },
            "required": ["goal"],
        },
    },
    {
        "name": "run_plan",
        "description": (
            "Builder/executor subagent. Executes a previously-produced Plan "
            "(by plan_id) or an inline Plan, fanning out parallel-marked steps. "
            "Returns per-step results and a final natural-language summary."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "plan_id": {"type": "string", "description": "Plan id returned by plan_task."},
                "plan": {"type": "object", "description": "Inline Plan object (alternative to plan_id)."},
            },
        },
    },
    {
        "name": "deep_agent",
        "description": (
            "One-shot deep-agent: plan_task -> run_plan -> summary. Use this "
            "for goals that should be planned and executed in a single call."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "goal": {"type": "string", "description": "The goal to achieve."},
                "context": {"type": "string", "description": "Optional context.", "default": ""},
            },
            "required": ["goal"],
        },
    },
    {
        "name": "sheet_get_rows",
        "description": (
            "Paginated rows from an enterprise collection, for spreadsheet-style "
            "display. Returns {collection, skip, limit, total, rows}."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "collection": {"type": "string", "enum": ["employees", "tickets", "documents"]},
                "skip": {"type": "integer", "minimum": 0, "default": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 50},
                "sort": {"type": "object", "description": "Optional {field: 1|-1} sort."},
            },
            "required": ["collection"],
        },
    },
    {
        "name": "sheet_update_cell",
        "description": (
            "Update a single field on a single row by _id. Mirrors a "
            "spreadsheet cell edit. Writes an audit_log entry."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "collection": {"type": "string", "enum": ["employees", "tickets", "documents"]},
                "_id": {"type": "string"},
                "field": {"type": "string"},
                "value": {
                    "description": "New value. JSON-typed (string, number, bool, array, object).",
                },
            },
            "required": ["collection", "_id", "field"],
        },
    },
    {
        "name": "sheet_insert_row",
        "description": (
            "Insert one row. _id may be supplied or auto-generated. Writes an "
            "audit_log entry."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "collection": {"type": "string", "enum": ["employees", "tickets", "documents"]},
                "doc": {"type": "object"},
            },
            "required": ["collection", "doc"],
        },
    },
    {
        "name": "sheet_delete_row",
        "description": "Delete one row by _id. Writes an audit_log entry with the prior doc.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "collection": {"type": "string", "enum": ["employees", "tickets", "documents"]},
                "_id": {"type": "string"},
            },
            "required": ["collection", "_id"],
        },
    },
    {
        "name": "sheet_apply_nl",
        "description": (
            "Apply a plain-English edit instruction to one of the enterprise "
            "collections. Plans a sequence of cell/insert/delete ops and applies "
            "them through the same audited write-layer the spreadsheet UI uses. "
            "Returns markdown + JSON with applied/failed/summary."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "collection": {"type": "string", "enum": ["employees", "tickets", "documents"]},
                "instruction": {
                    "type": "string",
                    "description": "Plain-English edit, e.g. \"set Alice's dept to Platform\".",
                },
            },
            "required": ["collection", "instruction"],
        },
    },
    {
        "name": "wrangler_sample",
        "description": (
            "Light recent-doc sample for the aggregation builder. Returns the "
            "sampled rows plus a per-field summary (types, cardinality, coverage, "
            "examples) the UI turns into clickable field chips."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "collection": {"type": "string", "enum": ["employees", "tickets", "documents"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            "required": ["collection"],
        },
    },
    {
        "name": "wrangler_run_prefix",
        "description": (
            "Run a prefix of an aggregation pipeline (stages 0..upto) so each "
            "stage can be executed on its own. Returns the preview rows plus "
            "input_count -> output_count for the final stage. Goes through the "
            "same read-only validate_spec/aggregate path as mongo_aggregate."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "collection": {"type": "string", "enum": ["employees", "tickets", "documents"]},
                "pipeline": {"type": "array", "items": {"type": "object"}},
                "upto": {"type": "integer", "minimum": 0, "description": "Index of the last stage to run."},
            },
            "required": ["collection", "pipeline", "upto"],
        },
    },
    {
        "name": "wrangler_save_pipeline",
        "description": (
            "Persist a builder pipeline to db.wrangler_pipelines (upsert by id). "
            "Writes an audit_log row tagged source=wrangler_save."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "collection": {"type": "string", "enum": ["employees", "tickets", "documents"]},
                "stages": {"type": "array", "items": {"type": "object"}},
                "_id": {"type": "string", "description": "Optional id to update an existing pipeline."},
            },
            "required": ["name", "collection", "stages"],
        },
    },
    {
        "name": "wrangler_list_pipelines",
        "description": "List saved builder pipelines, optionally filtered to one collection.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "collection": {"type": "string", "enum": ["employees", "tickets", "documents"]},
            },
        },
    },
    {
        "name": "wrangler_suggest",
        "description": (
            "Ask the planner LLM for 2-3 useful, differently-shaped aggregation "
            "pipelines for a collection (count-by-group, trend-over-time, rank/top-N). "
            "Each suggestion is validated server-side; invalid ones are dropped."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "collection": {"type": "string", "enum": ["employees", "tickets", "documents"]},
            },
            "required": ["collection"],
        },
    },
    {
        "name": "audit_recent",
        "description": (
            "Return the most recent write audit-log entries (newest first) for the "
            "admin Overview activity feed. Read-only against the audit collection."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 25},
            },
        },
    },
    {
        "name": "workflow_run",
        "description": "Trigger/Step/Resume a compliance audit finding workflow runner lifecycle step.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "finding_id": {"type": "string", "description": "The string _id of the compliance audit finding."},
                "resume_decision": {"type": "string", "description": "Optional human approval input ('approve' or 'reject') to resume an interrupted workflow run."},
                "checkpoint_id": {"type": "string", "description": "Optional thread id of the run to resume. Defaults to run-<finding_id>."}
            },
            "required": ["finding_id"]
        }
    },
    {
        "name": "report_pdf",
        "description": "Aggregate findings and change events into a beautifully formatted narrative compliance PDF audit artifact.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "finding_id": {"type": "string", "description": "The compliance audit finding Identifier string."}
            },
            "required": ["finding_id"]
        }
    },
    {
        "name": "report_ppt",
        "description": "Aggregate compliance evidence and live database query logging proofs into an executive summary slide deck presentation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "finding_id": {"type": "string", "description": "The compliance audit finding Identifier string."}
            },
            "required": ["finding_id"]
        }
    }
]

# Stage 12 — cross-system topology graph for the Architecture page.
TOOLS.append({
    "name": "topology_graph",
    "description": "Return the cross-system interconnectivity graph (nodes, edges, concerns) for the Architecture visualization.",
    "inputSchema": {"type": "object", "properties": {}},
})

# Stage 18 — architecture graph v2 for the Architecture page.
TOOLS.append({
    "name": "architecture_graph",
    "description": "Return the architecture graph v2 (layers, nodes, edges, flows, concerns) for the enterprise topology / data-flow Architecture visualization.",
    "inputSchema": {"type": "object", "properties": {}},
})

# Stage 11 — compliance command-center overview roll-up.
TOOLS.append({
    "name": "overview_summary",
    "description": "Return the compliance command-center roll-up: KPIs, the ranked attention list (points of concern), connector health, and recent rows of the key compliance collections.",
    "inputSchema": {"type": "object", "properties": {}},
})

# Stage 20 — Standup Jira cockpit dry-run planning helpers.
TOOLS.extend([
    {
        "name": "standup_link_context",
        "description": "Parse standup chat messages for Jira/Confluence/GitHub/SNOW/Archer links, @mentions, and Jira issue keys. Performs no writes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "messages": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "author": {"type": "string"},
                            "body": {"type": "string"},
                            "kind": {"type": "string"},
                            "created_at": {"type": "string"},
                        },
                        "required": ["body"],
                    },
                },
                "selected_issues": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["messages"],
        },
    },
    {
        "name": "standup_summarize",
        "description": "Summarize standup chat and selected Jira context into proposed/dry-run follow-ups. Does not stage or write to external systems.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "messages": {"type": "array", "items": {"type": "object"}},
                "selected_issues": {"type": "array", "items": {"type": "object"}},
                "docs_context": {"type": "array", "items": {"type": "object"}},
                "trigger": {"type": "string", "default": "manual"},
                "max_messages": {"type": "integer", "minimum": 1, "maximum": 500, "default": 80},
            },
            "required": ["messages"],
        },
    },
    {
        "name": "standup_templates",
        "description": "List backend-owned Standup Jira/Confluence prompt templates shared by the Templates panel and Deep Agent context packs. Read-only.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "standup_incoming_tickets",
        "description": "Stage 31 read-only scan of unassigned/new Jira intake tickets with entity extraction, workflow matching, and connector-hub enrichment.",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 25, "default": 10}},
        },
    },
    {
        "name": "identity_enrichment",
        "description": "Stage 32 read-only identity enrichment: resolve LDAP fixture user, infer team(s), and gather connector-hub context.",
        "inputSchema": {"type": "object", "properties": {"identity": {"type": "string"}}, "required": ["identity"]},
    },
])

# Stage 14 — docs wiki CRUD/search/sync/agent tools.
TOOLS.extend([
    {
        "name": "docs_list",
        "description": "List wiki docs as a path-grouped nav tree plus a review queue (needs_attention/archivable). Filter by tag/status/visibility. Bodies omitted.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tag": {"type": "string"},
                "status": {"type": "string", "enum": ["up_to_date", "needs_attention", "archivable", "archived"]},
                "visibility": {"type": "string", "enum": ["internal", "public"]},
                "include_archived": {"type": "boolean", "default": False},
            },
        },
    },
    {
        "name": "docs_get",
        "description": "Get one wiki doc (full Markdown body) by slug, with its revision history and recent Confluence sync events.",
        "inputSchema": {
            "type": "object",
            "properties": {"slug": {"type": "string"}},
            "required": ["slug"],
        },
    },
    {
        "name": "docs_upsert",
        "description": "Create or update a wiki doc by slug. Writes an append-only doc_revisions entry and bumps version. Audited (source=docs_upsert).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "title": {"type": "string"},
                "body_md": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "status": {"type": "string", "enum": ["up_to_date", "needs_attention", "archivable", "archived"]},
                "visibility": {"type": "string", "enum": ["internal", "public"]},
                "owner": {"type": "string"},
                "note": {"type": "string"},
            },
            "required": ["slug"],
        },
    },
    {
        "name": "docs_set_flags",
        "description": "Set lifecycle status / visibility / tags on a wiki doc (no content revision). Audited (source=docs_set_flags).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "status": {"type": "string", "enum": ["up_to_date", "needs_attention", "archivable", "archived"]},
                "visibility": {"type": "string", "enum": ["internal", "public"]},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["slug"],
        },
    },
    {
        "name": "docs_search",
        "description": "Search wiki docs by title, body, or tag (case-insensitive substring).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 25},
            },
            "required": ["query"],
        },
    },
    {
        "name": "docs_sync",
        "description": "Reconcile public wiki docs to Confluence (mirroring the path tree). Dry-run by default; gated by DOCS_SYNC_ENABLED + CONN_CONFLUENCE_ENABLED + WORKFLOW_WRITES_ENABLED. Logs every action to doc_sync_log.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "slug": {"type": "string", "description": "Optional: sync just one doc. Default: all public docs."},
            },
        },
    },
    {
        "name": "docs_agent_run",
        "description": "Docs agent LangGraph workflow: reconcile (sync) → triage (flag stale/unreferenced) → suggest (draft improvement proposals) → apply-gate (human-in-the-loop interrupt). A fresh run pauses at the gate with status='waiting_approval' and returns a run_id + proposals; resume it by calling again with that run_id and a resume_decision (slugs to apply, 'all', or 'reject') to apply only approved suggestions via an audited docs_upsert.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit_suggestions": {"type": "integer", "minimum": 0, "maximum": 10, "default": 3},
                "run_id": {"type": "string", "description": "Run id from a prior waiting_approval response; required to resume."},
                "resume_decision": {"description": "Apply decision to resume an interrupted run: a list of slugs, a comma-separated string, 'all'/'approve', or 'reject'/'none'."},
            },
        },
    },
])

# Stage 9 — append connector tools dynamically after the static list is defined.
TOOLS.extend(connector_tools())

# Stage 21 — Deep Agent platform runtime API.
TOOLS.extend([
    {
        "name": "agent_profiles_list",
        "description": "List Deep Agent platform agents: scopes, write policy, required capability, allowed/write tools.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "chat_runtime_info",
        "description": (
            "Report the active LLM runtime routing for the chat agent and the "
            "Deep Agent platform: provider, redacted endpoint (host+path only, "
            "never keys), and model for the public chat agent plus each system "
            "agent/role. Read-only runtime visibility (Stage 26)."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "agent_run_start",
        "description": (
            "Start a Deep Agent run. Routes the goal to one system agent (or the "
            "named `agent`) and runs to the first HITL pause or completion. "
            "Dry-run by default."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "goal": {"type": "string", "description": "What to accomplish."},
                "agent": {"type": "string", "description": "Optional agent name; omit to let the orchestrator route."},
                "context_refs": {"type": "array", "items": {"type": "string"}, "default": []},
                "mode": {"type": "string", "enum": ["dry_run", "live"], "default": "dry_run"},
                "actor": {"type": "string", "description": "Caller identity for audit.", "default": ""},
            },
            "required": ["goal"],
        },
    },
    {
        "name": "agent_run_status",
        "description": "Inspect a Deep Agent run: status, result text, pending approval, artifacts.",
        "inputSchema": {
            "type": "object",
            "properties": {"run_id": {"type": "string"}},
            "required": ["run_id"],
        },
    },
    {
        "name": "agent_run_resume",
        "description": (
            "Resume a waiting_approval run with approve / reject / edited payload. "
            "Approving or editing a capability-gated write requires the actor to hold "
            "the agent profile's required_capability (pass actor_capabilities)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
                "decision": {"description": "true/'approve', false/'reject', or an edited payload object."},
                "actor": {"type": "string", "default": ""},
                "actor_capabilities": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": [],
                    "description": "The resuming actor's Stage-19 capabilities (for the write capability gate).",
                },
            },
            "required": ["run_id", "decision"],
        },
    },
    {
        "name": "agent_run_cancel",
        "description": "Cancel a Deep Agent run and persist a terminal state.",
        "inputSchema": {
            "type": "object",
            "properties": {"run_id": {"type": "string"}},
            "required": ["run_id"],
        },
    },
    {
        "name": "agent_run_artifacts",
        "description": "Fetch generated artifacts (proposals/reports/docs/patches) for a run.",
        "inputSchema": {
            "type": "object",
            "properties": {"run_id": {"type": "string"}},
            "required": ["run_id"],
        },
    },
])


# ---------------------------------------------------------------------------
# Connector tools (proxied through registry)
# ---------------------------------------------------------------------------


async def _tool_connector_health(args: dict[str, Any]) -> dict[str, Any]:
    name = args.get("name")
    conn = get_connector(name) if name else None
    if conn is None:
        return {"content": [{"type": "text", "text": f"Connector '{name}' not found. Registered: {[c.name for c in list_connectors()]}"}], "isError": True}
    result = await conn.health()
    return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}], "isError": False}


async def _tool_connector_summary(args: dict[str, Any]) -> dict[str, Any]:
    name = args.get("name")
    conn = get_connector(name) if name else None
    if conn is None:
        return {"content": [{"type": "text", "text": f"Connector '{name}' not found. Registered: {[c.name for c in list_connectors()]}"}], "isError": True}
    result = await conn.summary()
    return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}], "isError": False}


async def _tool_topology_graph(args: dict[str, Any]) -> dict[str, Any]:
    graph = await build_topology()
    return {"content": [{"type": "text", "text": json.dumps(graph, indent=2)}], "isError": False}


async def _tool_architecture_graph(args: dict[str, Any]) -> dict[str, Any]:
    graph = await build_architecture()
    return {"content": [{"type": "text", "text": json.dumps(graph, indent=2)}], "isError": False}


async def _tool_overview_summary(args: dict[str, Any]) -> dict[str, Any]:
    payload = await build_overview()
    return {"content": [{"type": "text", "text": json.dumps(payload, indent=2)}], "isError": False}


# ---------------------------------------------------------------------------
# Stage 14 — docs wiki tools
# ---------------------------------------------------------------------------


def _docs_envelope(md: str, payload: Any, *, is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [
            {"type": "text", "text": md},
            {"type": "text", "text": json.dumps(payload, indent=2, default=str)},
        ],
        "isError": is_error,
    }


def _standup_envelope(payload: Any, *, is_error: bool = False) -> dict[str, Any]:
    md = standupmod.render_markdown(payload) if isinstance(payload, dict) else str(payload)
    return {
        "content": [
            {"type": "text", "text": md},
            {"type": "text", "text": json.dumps(payload, indent=2, default=str)},
        ],
        "isError": is_error,
    }


async def _tool_standup_link_context(args: dict[str, Any]) -> dict[str, Any]:
    payload = standupmod.build_link_context(
        args.get("messages") or [],
        selected_issues=args.get("selected_issues") or [],
    )
    return _standup_envelope(payload)


async def _tool_standup_summarize(args: dict[str, Any]) -> dict[str, Any]:
    try:
        payload = await standupmod.run_standup_summarize(
            args.get("messages") or [],
            selected_issues=args.get("selected_issues") or [],
            docs_context=args.get("docs_context") or [],
            trigger=args.get("trigger") or "manual",
            max_messages=int(args.get("max_messages", 80) or 80),
        )
    except standupmod.UnsupportedStandupModel as e:
        return _standup_envelope({"error": str(e), "code": "unsupported_model"}, is_error=True)
    except Exception as e:  # noqa: BLE001
        return _standup_envelope({"error": f"{type(e).__name__}: {e}"}, is_error=True)
    return _standup_envelope(payload)


async def _tool_standup_templates(args: dict[str, Any]) -> dict[str, Any]:
    payload = standuptemplatesmod.payload()
    return {
        "content": [
            {"type": "text", "text": standuptemplatesmod.render_markdown(payload)},
            {"type": "text", "text": json.dumps(payload, indent=2, default=str)},
        ],
        "isError": not payload.get("enabled", False),
    }


async def _tool_standup_incoming_tickets(args: dict[str, Any]) -> dict[str, Any]:
    jira_issues: list[dict[str, Any]] = []
    connector_summaries: dict[str, Any] = {}
    try:
        jira = get_connector("jira")
        if jira is not None:
            listed = await jira.dispatch("jira_list_issues", {})
            blocks = [c.get("text", "") for c in listed.get("content", []) if c.get("type") == "text"]
            for text in reversed(blocks):
                try:
                    parsed = json.loads(text)
                    rows = parsed.get("issues") or parsed.get("rows") or parsed
                    if isinstance(rows, list):
                        jira_issues = [row for row in rows if isinstance(row, dict)]
                        break
                except (TypeError, json.JSONDecodeError):
                    continue
    except Exception as e:  # noqa: BLE001
        connector_summaries["jira"] = {"status": "degraded", "detail": f"{type(e).__name__}: {e}"}
    for name in ("aws", "servicenow", "github", "mongodb", "jira"):
        try:
            conn = get_connector(name)
            if conn is not None:
                connector_summaries[name] = await conn.summary()
        except Exception as e:  # noqa: BLE001
            connector_summaries[name] = {"status": "degraded", "detail": f"{type(e).__name__}: {e}"}
    async def _identity_builder(identity: str) -> dict[str, Any]:
        connectors = {n: get_connector(n) for n in ("servicenow", "github", "mongodb", "confluence") if get_connector(n) is not None}
        return await build_identity_enrichment(identity, ldap_connector=get_connector("ldap"), connectors=connectors)

    payload = await standupintakemod.build_incoming_tickets(
        jira_issues,
        limit=int(args.get("limit") or 10),
        connector_summaries=connector_summaries,
        identity_builder=_identity_builder,
    )
    return {
        "content": [
            {"type": "text", "text": standupintakemod.render_markdown(payload)},
            {"type": "text", "text": json.dumps(payload, indent=2, default=str)},
        ],
        "isError": False,
    }


async def _tool_identity_enrichment(args: dict[str, Any]) -> dict[str, Any]:
    connectors = {name: get_connector(name) for name in ("servicenow", "github", "mongodb", "confluence") if get_connector(name) is not None}
    payload = await build_identity_enrichment(str(args.get("identity") or ""), ldap_connector=get_connector("ldap"), connectors=connectors)
    return {
        "content": [
            {"type": "text", "text": render_identity_enrichment_markdown(payload)},
            {"type": "text", "text": json.dumps(payload, indent=2, default=str)},
        ],
        "isError": False,
    }


async def _tool_docs_list(args: dict[str, Any]) -> dict[str, Any]:
    payload = await docsmod.build_tree(
        tag=args.get("tag"),
        status=args.get("status"),
        visibility=args.get("visibility"),
        include_archived=bool(args.get("include_archived", False)),
    )
    lines = [f"# Docs ({payload['count']})", ""]
    for grp in payload["tree"]:
        lines.append(f"## {grp['group']}")
        for d in grp["docs"]:
            lines.append(f"- **{d.get('title')}** `{d.get('slug')}` — {d.get('derived_status')} · {d.get('visibility')}")
    if payload["review_queue"]:
        lines += ["", f"## Review queue ({len(payload['review_queue'])})"]
        for r in payload["review_queue"]:
            lines.append(f"- {r['title']} (`{r['slug']}`) → {r['status']}")
    return _docs_envelope("\n".join(lines), payload)


async def _tool_docs_get(args: dict[str, Any]) -> dict[str, Any]:
    slug = args.get("slug")
    doc = await docsmod.get_doc(slug)
    if doc is None:
        return _docs_envelope(f"No doc with slug `{slug}`.", {"error": "not_found", "slug": slug}, is_error=True)
    md = f"# {doc.get('title')}\n\n_v{doc.get('version')} · {doc.get('derived_status')} · {doc.get('visibility')}_\n\n{doc.get('body_md','')}"
    return _docs_envelope(md, doc)


async def _tool_docs_upsert(args: dict[str, Any]) -> dict[str, Any]:
    result = await dbmod.docs_upsert(
        slug=args["slug"],
        title=args.get("title"),
        body_md=args.get("body_md"),
        tags=args.get("tags"),
        status=args.get("status"),
        visibility=args.get("visibility"),
        owner=args.get("owner"),
        note=args.get("note", "") or "",
        source="docs_upsert",
    )
    verb = "Created" if result["created"] else "Updated"
    md = f"{verb} `{result['doc']['slug']}` → v{result['doc']['version']}."
    return _docs_envelope(md, result)


async def _tool_docs_set_flags(args: dict[str, Any]) -> dict[str, Any]:
    result = await dbmod.docs_set_flags(
        slug=args["slug"],
        status=args.get("status"),
        visibility=args.get("visibility"),
        tags=args.get("tags"),
        source="docs_set_flags",
    )
    d = result["doc"]
    md = f"Flags set on `{d['slug']}`: status={d.get('status')} visibility={d.get('visibility')} tags={d.get('tags')}."
    return _docs_envelope(md, result)


async def _tool_docs_search(args: dict[str, Any]) -> dict[str, Any]:
    rows = await dbmod.docs_search(args["query"], limit=int(args.get("limit", 25) or 25))
    md = f"# Search: {args['query']} ({len(rows)} hits)\n\n" + "\n".join(
        f"- **{r.get('title')}** `{r.get('slug')}`" for r in rows
    )
    return _docs_envelope(md, {"query": args["query"], "results": rows})


async def _tool_docs_sync(args: dict[str, Any]) -> dict[str, Any]:
    from docs_sync import run_docs_sync

    payload = await run_docs_sync(slug=args.get("slug"))
    md_lines = [
        f"# Docs → Confluence sync ({'LIVE' if payload['live'] else 'DRY-RUN'})",
        f"- space: `{payload['space']}`",
        f"- considered: {payload['considered']} public doc(s)",
        "",
        "## Plan",
    ]
    for a in payload["actions"]:
        md_lines.append(f"- `{a['slug']}` → **{a['action']}** (page `{a.get('confluence_page_id') or '—'}`) {a.get('detail','')}")
    return _docs_envelope("\n".join(md_lines), payload)


async def _tool_docs_agent_run(args: dict[str, Any]) -> dict[str, Any]:
    from docs_agent import run_docs_agent_graph

    payload = await run_docs_agent_graph(
        limit_suggestions=int(args.get("limit_suggestions", 3) or 3),
        run_id=args.get("run_id"),
        resume_decision=args.get("resume_decision", None),
    )
    md_lines = ["# Docs agent run", ""]
    md_lines.append(f"_run `{payload['run_id']}` · status **{payload['status']}**_")
    rec = payload.get("reconcile", {})
    md_lines.append(
        f"\n**Reconcile:** {rec.get('considered', 0)} public doc(s), {len(rec.get('actions', []))} action(s)."
    )
    md_lines.append(f"**Triage:** {len(payload['triage'])} doc(s) flagged.")
    for t in payload["triage"]:
        md_lines.append(f"- `{t['slug']}` → {t['suggested_status']} ({t['reason']})")
    md_lines.append(f"\n**Suggestions (proposals):** {len(payload['suggestions'])}")
    for s in payload["suggestions"]:
        flag = " ✅ applied" if s.get("applied") else ""
        md_lines.append(f"- `{s['slug']}`: {s['rationale']}{flag}")
    if payload["status"] == "waiting_approval":
        md_lines.append(
            f"\n_Paused at the apply gate. Resume with `docs_agent_run(run_id=\"{payload['run_id']}\", "
            f"resume_decision=<slugs | 'all' | 'reject'>)` to apply approved proposals._"
        )
    else:
        applied = payload.get("applied", [])
        md_lines.append(f"\n**Applied:** {len(applied)} revision(s) (audited).")
        for a in applied:
            if a.get("error"):
                md_lines.append(f"- `{a['slug']}`: error — {a['error']}")
            else:
                md_lines.append(f"- `{a['slug']}` → v{a.get('version')}")
    return _docs_envelope("\n".join(md_lines), payload)


async def _tool_workflow_run(args: dict[str, Any]) -> dict[str, Any]:
    finding_id = args.get("finding_id")
    if not finding_id:
        return {"content": [{"type": "text", "text": "finding_id is required."}], "isError": True}

    res = await run_compliance_workflow(
        finding_id=finding_id,
        resume_decision=args.get("resume_decision"),
        checkpoint_id=args.get("checkpoint_id"),
    )

    md_lines = [
        f"# Compliance Workflow Run",
        f"- **Run ID:** `{res['run_id']}`",
        f"- **Workflow Status:** `{res['status'].upper()}`",
        f"- **Current Step Index:** `{res['step_index']}/6`",
    ]
    if res.get("next_action_preview"):
        preview = res["next_action_preview"] or {}
        msg = preview.get("message", "Approve step?")
        md_lines.append(f"- **Awaiting Approval:** *{msg}*")

    md_lines.append("\n## Current Artifacts")
    for key, val in res.get("artifacts", {}).items():
        if key in ("finding", "epic", "ticket_payload", "pr_spec", "confluence_doc_text"):
            # Truncate large dicts in summary view
            md_lines.append(f"- **{key}:** *populated (dictionary)*")
        else:
            md_lines.append(f"- **{key}:** `{val}`")

    return {
        "content": [
            {"type": "text", "text": "\n".join(md_lines)},
            {"type": "text", "text": json.dumps(res, indent=2, default=str)},
        ],
        "isError": False,
    }


async def _tool_report_pdf(args: dict[str, Any]) -> dict[str, Any]:
    finding_id = args.get("finding_id")
    if not finding_id:
        return {"content": [{"type": "text", "text": "finding_id is required."}], "isError": True}

    output_dir = "/sandbox/reports"
    try:
        path = await generate_pdf_report(finding_id, output_dir)
        summary = f"### Compliance Audit PDF Report Generated Successfully\n- **Target path:** `{path}`\n- **Details:** Contains full compliance metrics, change tickets, Github branch mappings, Confluence wiki documentation, and live audit event log samples."
        return {
            "content": [
                {"type": "text", "text": summary},
                {"type": "text", "text": json.dumps({"status": "success", "filepath": path})}
            ],
            "isError": False
        }
    except Exception as e:  # noqa: BLE001
        import traceback
        tb = traceback.format_exc()
        print(f"[mcp tool error] report_pdf failed\n{tb}", flush=True)
        return {"content": [{"type": "text", "text": f"Failed to compile PDF Report: {type(e).__name__}: {e}"}], "isError": True}


async def _tool_report_ppt(args: dict[str, Any]) -> dict[str, Any]:
    finding_id = args.get("finding_id")
    if not finding_id:
        return {"content": [{"type": "text", "text": "finding_id is required."}], "isError": True}

    output_dir = "/sandbox/reports"
    try:
        path = await generate_ppt_report(finding_id, output_dir)
        summary = f"### Executive Summary compliance Deck Generated Successfully\n- **Target path:** `{path}`\n- **Details:** Includes title milestone track lists, platform coverage profiles, SQL database evidence logs, and strategic compliance roadmap recomendations."
        return {
            "content": [
                {"type": "text", "text": summary},
                {"type": "text", "text": json.dumps({"status": "success", "filepath": path})}
            ],
            "isError": False
        }
    except Exception as e:  # noqa: BLE001
        import traceback
        tb = traceback.format_exc()
        print(f"[mcp tool error] report_ppt failed\n{tb}", flush=True)
        return {"content": [{"type": "text", "text": f"Failed to generate Slide Deck: {type(e).__name__}: {e}"}], "isError": True}


async def _upstream_chat(messages: list[dict[str, str]]) -> str:
    payload = {
        "model": UPSTREAM_MODEL,
        "messages": messages,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    headers = {"Authorization": f"Bearer {UPSTREAM_API_KEY}"}
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        r = await client.post(f"{UPSTREAM_BASE_URL}/chat/completions", json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
    return data["choices"][0]["message"]["content"]


async def _tool_summarize_text(args: dict[str, Any]) -> str:
    text = args["text"]
    max_words = int(args.get("max_words", 80))
    system = (
        "You are a concise summarizer. Produce a single paragraph capturing the key points "
        f"of the user's text in at most {max_words} words. Do not editorialize."
    )
    return await _upstream_chat(
        [{"role": "system", "content": system}, {"role": "user", "content": text}]
    )


async def _tool_chat(args: dict[str, Any]) -> str:
    messages = list(args["messages"])
    if (system := args.get("system")):
        messages = [{"role": "system", "content": system}, *messages]
    return await _upstream_chat(messages)


def _tool_echo(args: dict[str, Any]) -> str:
    return str(args.get("value", ""))


async def _tool_web_research(args: dict[str, Any]) -> list[dict[str, Any]]:
    topic = args["topic"]
    k = int(args.get("k", 5))
    payload = await run_web_research(topic, k=k)
    markdown = render_web_research_markdown(payload)
    return [
        {"type": "text", "text": markdown},
        {"type": "text", "text": json.dumps(payload, indent=2, ensure_ascii=False, default=str)},
    ]


# ---------------------------------------------------------------------------
# Mongo / ask_data tools
# ---------------------------------------------------------------------------


def _markdown_table(rows: list[dict[str, Any]], max_rows: int = 10) -> str:
    if not rows:
        return "_no rows_"
    columns: list[str] = []
    for r in rows[:max_rows]:
        for k in r.keys():
            if k not in columns:
                columns.append(k)
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for r in rows[:max_rows]:
        cells = []
        for c in columns:
            v = r.get(c, "")
            if isinstance(v, (dict, list)):
                v = json.dumps(v, default=str)
            cells.append(str(v).replace("|", "\\|"))
        lines.append("| " + " | ".join(cells) + " |")
    if len(rows) > max_rows:
        lines.append(f"\n_({len(rows) - max_rows} more rows omitted)_")
    return "\n".join(lines)


async def _tool_mongo_list_collections(args: dict[str, Any]) -> list[dict[str, Any]]:
    rows = await dbmod.list_collections()
    md = "# Collections\n\n" + _markdown_table(rows)
    return [
        {"type": "text", "text": md},
        {"type": "text", "text": json.dumps({"collections": rows}, indent=2)},
    ]


async def _tool_mongo_describe_collection(args: dict[str, Any]) -> list[dict[str, Any]]:
    name = args["name"]
    sample = int(args.get("sample", 5))
    desc = await dbmod.describe_collection(name, sample=sample)
    lines = [f"# {desc['collection']} (sampled {desc['sample_size']})", ""]
    for fname, info in desc["fields"].items():
        lines.append(f"- **{fname}** _({'|'.join(info['types'])})_ e.g. `{info['example']}`")
    md = "\n".join(lines)
    return [
        {"type": "text", "text": md},
        {"type": "text", "text": json.dumps(desc, indent=2, default=str)},
    ]


async def _tool_mongo_query(args: dict[str, Any]) -> list[dict[str, Any]]:
    spec = {
        "collection": args["collection"],
        "kind": "find",
        "filter": args.get("filter") or {},
    }
    for k in ("projection", "sort", "limit", "skip"):
        if k in args and args[k] is not None:
            spec[k] = args[k]
    rows = await dbmod.find(spec)
    md = f"# mongo_query: {args['collection']}\n\n" + _markdown_table(rows)
    return [
        {"type": "text", "text": md},
        {"type": "text", "text": json.dumps({"rows": rows}, indent=2, default=str)},
    ]


async def _tool_mongo_aggregate(args: dict[str, Any]) -> list[dict[str, Any]]:
    spec = {
        "collection": args["collection"],
        "kind": "aggregate",
        "pipeline": args["pipeline"],
    }
    if "limit" in args and args["limit"] is not None:
        spec["limit"] = args["limit"]
    rows = await dbmod.aggregate(spec)
    md = f"# mongo_aggregate: {args['collection']}\n\n" + _markdown_table(rows)
    return [
        {"type": "text", "text": md},
        {"type": "text", "text": json.dumps({"rows": rows}, indent=2, default=str)},
    ]


# ---------------------------------------------------------------------------
# Sandbox tools (stage 4)
# ---------------------------------------------------------------------------


async def _tool_fs_read(args: dict[str, Any]) -> list[dict[str, Any]]:
    text = sbx.fs_read(args["path"])
    return [{"type": "text", "text": text}]


async def _tool_fs_write(args: dict[str, Any]) -> list[dict[str, Any]]:
    info = sbx.fs_write(args["path"], args.get("content", ""))
    return [{"type": "text", "text": json.dumps(info, indent=2)}]


async def _tool_fs_edit(args: dict[str, Any]) -> list[dict[str, Any]]:
    info = sbx.fs_edit(args["path"], args["old_string"], args["new_string"])
    return [{"type": "text", "text": json.dumps(info, indent=2)}]


async def _tool_shell_exec(args: dict[str, Any]) -> list[dict[str, Any]]:
    result = await sbx.shell_exec(args["cmd"], timeout_sec=args.get("timeout_sec"))
    head = f"$ {result['cmd']}\nexit={result['exit_code']}{' (timed out)' if result['timed_out'] else ''}\n"
    body = ""
    if result["stdout"]:
        body += "--- stdout ---\n" + result["stdout"] + "\n"
    if result["stderr"]:
        body += "--- stderr ---\n" + result["stderr"] + "\n"
    return [
        {"type": "text", "text": head + body},
        {"type": "text", "text": json.dumps(result, indent=2)},
    ]


# ---------------------------------------------------------------------------
# Deep-agent tools (stage 4)
# ---------------------------------------------------------------------------


def _plan_markdown(plan: Plan) -> str:
    lines = [f"# Plan {plan.plan_id or '(new)'}", "", f"**Goal:** {plan.goal}", ""]
    if plan.rationale:
        lines += [plan.rationale, ""]
    lines.append("## Steps")
    for s in plan.steps:
        deps = ", ".join(s.depends_on) or "—"
        par = " · parallel" if s.parallel else ""
        lines.append(f"- **{s.id}** → `{s.tool}` (deps: {deps}){par}")
        if s.rationale:
            lines.append(f"  - {s.rationale}")
    return "\n".join(lines)


async def _tool_plan_task(args: dict[str, Any]) -> dict[str, Any]:
    goal = args.get("goal")
    if not goal:
        return {"content": [{"type": "text", "text": "goal is required"}], "isError": True}
    result = await run_plan_task(goal, context=args.get("context", "") or "")
    if "error" in result:
        return {
            "content": [{"type": "text", "text": f"[planner error] {result['error']}"}],
            "isError": True,
        }
    plan: Plan = result["plan"]
    return {
        "content": [
            {"type": "text", "text": _plan_markdown(plan)},
            {"type": "text", "text": plan.model_dump_json(indent=2)},
        ],
        "isError": False,
    }


async def _tool_run_plan(args: dict[str, Any]) -> dict[str, Any]:
    plan = None
    if args.get("plan"):
        try:
            plan = Plan.model_validate(args["plan"])
        except Exception as e:  # noqa: BLE001
            return {
                "content": [{"type": "text", "text": f"[plan validation error] {e}"}],
                "isError": True,
            }
    summary = await run_run_plan(plan=plan, plan_id=args.get("plan_id"))
    md_lines = [f"# Run of plan {summary.plan_id}", "", f"**Goal:** {summary.goal}", ""]
    if summary.replanned:
        md_lines.append("_(plan was re-planned once after a step failure)_")
    if summary.error:
        md_lines += ["", f"**Error:** {summary.error}"]
    md_lines.append("\n## Step results")
    for r in summary.results:
        if r.status == "ok":
            md_lines.append(f"- **{r.step_id}** ✓")
            if r.output:
                snippet = r.output if len(r.output) < 400 else r.output[:400] + "…"
                md_lines.append(f"  > {snippet}")
        else:
            md_lines.append(f"- **{r.step_id}** ✗ {r.error}")
    if summary.summary:
        md_lines += ["", "## Summary", summary.summary]
    return {
        "content": [
            {"type": "text", "text": "\n".join(md_lines)},
            {"type": "text", "text": summary.model_dump_json(indent=2)},
        ],
        "isError": bool(summary.error),
    }


async def _tool_deep_agent(args: dict[str, Any]) -> dict[str, Any]:
    goal = args.get("goal")
    if not goal:
        return {"content": [{"type": "text", "text": "goal is required"}], "isError": True}
    result = await run_deep_agent(goal, context=args.get("context", "") or "")
    if "error" in result:
        return {
            "content": [{"type": "text", "text": f"[deep_agent error] {result['error']}"}],
            "isError": True,
        }
    plan: Plan = result["plan"]
    summary = result["summary"]
    md = _plan_markdown(plan) + "\n\n"
    md += f"## Run\n\n"
    if summary.replanned:
        md += "_(plan was re-planned once after a step failure)_\n\n"
    for r in summary.results:
        if r.status == "ok":
            md += f"- **{r.step_id}** ✓\n"
        else:
            md += f"- **{r.step_id}** ✗ {r.error}\n"
    if summary.summary:
        md += f"\n## Summary\n\n{summary.summary}\n"
    payload = {"plan": plan.model_dump(), "summary": summary.model_dump()}
    return {
        "content": [
            {"type": "text", "text": md},
            {"type": "text", "text": json.dumps(payload, indent=2, default=str)},
        ],
        "isError": bool(summary.error),
    }


# ---------------------------------------------------------------------------
# Stage 21 — Deep Agent platform runtime tools
# ---------------------------------------------------------------------------


def _agent_envelope(payload: dict[str, Any], md: str, is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [
            {"type": "text", "text": md},
            {"type": "text", "text": json.dumps(payload, indent=2, default=str)},
        ],
        "isError": is_error,
    }


async def _tool_agent_profiles_list(args: dict[str, Any]) -> dict[str, Any]:
    from deep_agent.runtime import agent_profiles_list

    profiles = agent_profiles_list()
    lines = ["# Deep Agent profiles", ""]
    for p in profiles:
        wp = p["write_policy"]
        cap = p["required_capability"] or "—"
        lines.append(f"- **{p['name']}** ({wp}, cap: {cap}) — {p['description']}")
    return _agent_envelope({"agents": profiles}, "\n".join(lines))


async def _tool_chat_runtime_info(args: dict[str, Any]) -> dict[str, Any]:
    """Stage 26 — redacted view of which runtime answers chat + delegated work.

    The public chat agent (the `/v1/chat/completions` service) talks to the
    `default` role's upstream; the Deep Agent platform's orchestrator and
    system agents resolve to planner/builder/default roles. No keys are
    surfaced anywhere here."""
    from llm import role_runtime

    chat_agent = role_runtime("default")
    try:
        from deep_agent.runtime import runtime_info

        platform = runtime_info()
    except Exception as e:  # noqa: BLE001 — platform is optional; chat still reports
        platform = {"error": str(e), "roles": {}, "orchestrator": None, "agents": []}

    payload = {"chat_agent": chat_agent, "platform": platform}

    lines = [
        "# Chat runtime",
        "",
        f"**Chat agent** — provider `{chat_agent['provider']}`, "
        f"model `{chat_agent['model']}`, endpoint `{chat_agent['endpoint']}`",
    ]
    agents = platform.get("agents") or []
    if agents:
        lines += ["", "## Deep Agent delegation"]
        orch = platform.get("orchestrator")
        if orch:
            lines.append(
                f"- **orchestrator** ({orch['role']}) — `{orch['provider']}` / "
                f"`{orch['model']}`"
            )
        for a in agents:
            inh = " · inherits default" if a["inherits_default"] else ""
            lines.append(
                f"- **{a['name']}** ({a['role']}) — `{a['provider']}` / "
                f"`{a['model']}`{inh}"
            )
    return _agent_envelope(payload, "\n".join(lines))


async def _tool_agent_run_start(args: dict[str, Any]) -> dict[str, Any]:
    from deep_agent.runtime import AgentRunStartRequest, agent_run_start

    try:
        req = AgentRunStartRequest(
            goal=args.get("goal", ""),
            agent=args.get("agent") or None,
            context_refs=args.get("context_refs", []) or [],
            mode=args.get("mode", "dry_run"),
            actor=args.get("actor") or None,
        )
    except Exception as e:  # noqa: BLE001
        return _agent_envelope({"error": str(e)}, f"[agent_run_start] invalid request: {e}", True)
    rec = await agent_run_start(req)
    md = f"# Agent run `{rec.run_id}` · **{rec.status}**\n\n{rec.result_text[:1200]}"
    if rec.approval:
        md += f"\n\n_Paused for approval (tool: {rec.approval.tool or '—'}). Resume with agent_run_resume._"
    return _agent_envelope(rec.model_dump(), md, rec.status == "error")


async def _tool_agent_run_status(args: dict[str, Any]) -> dict[str, Any]:
    from deep_agent.runtime import agent_run_status

    rec = await agent_run_status(args.get("run_id", ""))
    if rec is None:
        return _agent_envelope({"error": "not found"}, "[agent_run_status] run not found", True)
    return _agent_envelope(rec.model_dump(), f"# Agent run `{rec.run_id}` · **{rec.status}**")


async def _tool_agent_run_resume(args: dict[str, Any]) -> dict[str, Any]:
    from deep_agent.runtime import PermissionDeniedError, agent_run_resume

    try:
        rec = await agent_run_resume(
            args.get("run_id", ""),
            args.get("decision"),
            actor=args.get("actor") or None,
            actor_capabilities=args.get("actor_capabilities") or [],
        )
    except PermissionDeniedError as e:
        return _agent_envelope({"error": str(e), "code": "forbidden"}, f"[agent_run_resume] {e}", True)
    except ValueError as e:
        return _agent_envelope({"error": str(e)}, f"[agent_run_resume] {e}", True)
    return _agent_envelope(rec.model_dump(), f"# Agent run `{rec.run_id}` · **{rec.status}**")


async def _tool_agent_run_cancel(args: dict[str, Any]) -> dict[str, Any]:
    from deep_agent.runtime import agent_run_cancel

    try:
        rec = await agent_run_cancel(args.get("run_id", ""))
    except ValueError as e:
        return _agent_envelope({"error": str(e)}, f"[agent_run_cancel] {e}", True)
    return _agent_envelope(rec.model_dump(), f"# Agent run `{rec.run_id}` · **{rec.status}**")


async def _tool_agent_run_artifacts(args: dict[str, Any]) -> dict[str, Any]:
    from deep_agent.runtime import agent_run_artifacts

    arts = await agent_run_artifacts(args.get("run_id", ""))
    return _agent_envelope({"artifacts": arts}, f"# Artifacts ({len(arts)})")


# ---------------------------------------------------------------------------
# Stage 6 — sheet tools (write surface + NL editor)
# ---------------------------------------------------------------------------


def _sheet_render_rows(payload: dict[str, Any]) -> str:
    rows = payload.get("rows", [])
    md = (
        f"# {payload['collection']} ({payload['skip']}..{payload['skip'] + len(rows)} of {payload['total']})\n\n"
        + _markdown_table(rows)
    )
    return md


async def _tool_sheet_get_rows(args: dict[str, Any]) -> list[dict[str, Any]]:
    payload = await dbmod.get_rows(
        args["collection"],
        skip=int(args.get("skip", 0) or 0),
        limit=int(args.get("limit", 50) or 50),
        sort=args.get("sort"),
    )
    return [
        {"type": "text", "text": _sheet_render_rows(payload)},
        {"type": "text", "text": json.dumps(payload, indent=2, default=str)},
    ]


async def _tool_sheet_update_cell(args: dict[str, Any]) -> list[dict[str, Any]]:
    # S19.audit.1 — actor is injected by the web layer; pop it before forwarding db args.
    actor = args.pop("actor", None) or None
    update: dict[str, Any]
    field = args["field"]
    if "value" in args:
        update = {"$set": {field: args["value"]}}
    else:
        update = {"$unset": {field: ""}}
    info = await dbmod.update_one(
        args["collection"], args["_id"], update, source="sheet_cell", actor=actor
    )
    return [
        {"type": "text", "text": json.dumps(info, indent=2, default=str)},
    ]


async def _tool_sheet_insert_row(args: dict[str, Any]) -> list[dict[str, Any]]:
    actor = args.pop("actor", None) or None  # S19.audit.1
    info = await dbmod.insert_one(args["collection"], args["doc"], source="sheet_insert", actor=actor)
    return [{"type": "text", "text": json.dumps(info, indent=2, default=str)}]


async def _tool_sheet_delete_row(args: dict[str, Any]) -> list[dict[str, Any]]:
    actor = args.pop("actor", None) or None  # S19.audit.1
    info = await dbmod.delete_one(args["collection"], args["_id"], source="sheet_delete", actor=actor)
    return [{"type": "text", "text": json.dumps(info, indent=2, default=str)}]


async def _tool_sheet_apply_nl(args: dict[str, Any]) -> dict[str, Any]:
    from sheet_apply import render_markdown as _sheet_render_md
    from sheet_apply import run_sheet_apply

    actor = args.pop("actor", None) or None  # S19.audit.1
    result = await run_sheet_apply(args["collection"], args["instruction"], actor)
    md = _sheet_render_md(result)
    payload = result.model_dump(exclude_none=True, by_alias=True)
    return {
        "content": [
            {"type": "text", "text": md},
            {"type": "text", "text": json.dumps(payload, indent=2, default=str)},
        ],
        "isError": bool(result.error),
    }


# ---------------------------------------------------------------------------
# Stage 7 — aggregation builder tools
# ---------------------------------------------------------------------------


async def _tool_wrangler_sample(args: dict[str, Any]) -> list[dict[str, Any]]:
    payload = await wranglermod.sample(args["collection"], limit=args.get("limit"))
    chips = "\n".join(
        f"- **{f['field']}** ({'|'.join(f['types'])}) "
        f"card={f['cardinality']} cov={f['coverage']}"
        for f in payload["field_summary"]
    )
    md = (
        f"# wrangler sample: {payload['collection']} "
        f"({payload['row_count']} rows by {payload['sort_field']} desc)\n\n{chips}"
    )
    return [
        {"type": "text", "text": md},
        {"type": "text", "text": json.dumps(payload, indent=2, default=str)},
    ]


async def _tool_wrangler_run_prefix(args: dict[str, Any]) -> list[dict[str, Any]]:
    payload = await wranglermod.run_prefix(
        args["collection"], args.get("pipeline") or [], int(args["upto"])
    )
    md = (
        f"# stage {payload['stage_index']} — "
        f"{payload['input_count']} → {payload['output_count']} rows\n\n"
        + _markdown_table(payload["rows"])
    )
    return [
        {"type": "text", "text": md},
        {"type": "text", "text": json.dumps(payload, indent=2, default=str)},
    ]


async def _tool_wrangler_save_pipeline(args: dict[str, Any]) -> list[dict[str, Any]]:
    info = await wranglermod.save_pipeline(
        args["name"], args["collection"], args.get("stages") or [], args.get("_id")
    )
    return [{"type": "text", "text": json.dumps(info, indent=2, default=str)}]


async def _tool_wrangler_list_pipelines(args: dict[str, Any]) -> list[dict[str, Any]]:
    info = await wranglermod.list_pipelines(args.get("collection"))
    return [{"type": "text", "text": json.dumps(info, indent=2, default=str)}]


async def _tool_audit_recent(args: dict[str, Any]) -> list[dict[str, Any]]:
    info = await dbmod.audit_recent(int(args.get("limit", 25) or 25))
    md = f"# audit_recent ({len(info['rows'])} rows)\n\n" + _markdown_table(info["rows"])
    return [
        {"type": "text", "text": md},
        {"type": "text", "text": json.dumps(info, indent=2, default=str)},
    ]


async def _tool_wrangler_suggest(args: dict[str, Any]) -> dict[str, Any]:
    from wrangler_suggest import run_wrangler_suggest

    result = await run_wrangler_suggest(args["collection"])
    md_lines = [f"# Suggested pipelines for {args['collection']}", ""]
    for p in result.get("pipelines", []):
        md_lines.append(f"## {p['name']}")
        if p.get("rationale"):
            md_lines.append(p["rationale"])
        md_lines.append(f"```json\n{json.dumps(p['stages'], indent=2)}\n```")
    return {
        "content": [
            {"type": "text", "text": "\n".join(md_lines)},
            {"type": "text", "text": json.dumps(result, indent=2, default=str)},
        ],
        "isError": not result.get("pipelines"),
    }


async def _tool_ask_data(args: dict[str, Any]) -> dict[str, Any]:
    question = args["question"]
    state = await run_ask_data(question)
    if state.final is None:
        md = render_ask_data_markdown(None, spec_error=state.spec_error, question=question)
        return {
            "content": [
                {"type": "text", "text": md},
                {"type": "text", "text": json.dumps({"spec_error": state.spec_error}, indent=2)},
            ],
            "isError": True,
        }
    md = render_ask_data_markdown(state.final, question=question)
    payload = state.final.model_dump(exclude_none=True)
    return {
        "content": [
            {"type": "text", "text": md},
            {"type": "text", "text": json.dumps(payload, indent=2, default=str)},
        ],
        "isError": False,
    }


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


async def _dispatch_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    # Tools returning a content list of multiple blocks.
    multi_content_tools = {
        "web_research": _tool_web_research,
        "mongo_list_collections": _tool_mongo_list_collections,
        "mongo_describe_collection": _tool_mongo_describe_collection,
        "mongo_query": _tool_mongo_query,
        "mongo_aggregate": _tool_mongo_aggregate,
        "fs_read": _tool_fs_read,
        "fs_write": _tool_fs_write,
        "fs_edit": _tool_fs_edit,
        "shell_exec": _tool_shell_exec,
        "sheet_get_rows": _tool_sheet_get_rows,
        "sheet_update_cell": _tool_sheet_update_cell,
        "sheet_insert_row": _tool_sheet_insert_row,
        "sheet_delete_row": _tool_sheet_delete_row,
        "wrangler_sample": _tool_wrangler_sample,
        "wrangler_run_prefix": _tool_wrangler_run_prefix,
        "wrangler_save_pipeline": _tool_wrangler_save_pipeline,
        "wrangler_list_pipelines": _tool_wrangler_list_pipelines,
        "audit_recent": _tool_audit_recent,
    }
    if name in multi_content_tools:
        try:
            content = await multi_content_tools[name](args)
        except sbx.SandboxError as e:
            return {"content": [{"type": "text", "text": f"[SandboxError] {e}"}], "isError": True}
        return {"content": content, "isError": False}

    if name == "ask_data":
        return await _tool_ask_data(args)
    if name == "standup_link_context":
        return await _tool_standup_link_context(args)
    if name == "standup_summarize":
        return await _tool_standup_summarize(args)
    if name == "standup_templates":
        return await _tool_standup_templates(args)
    if name == "standup_incoming_tickets":
        return await _tool_standup_incoming_tickets(args)
    if name == "identity_enrichment":
        return await _tool_identity_enrichment(args)
    if name == "docs_list":
        return await _tool_docs_list(args)
    if name == "docs_get":
        return await _tool_docs_get(args)
    if name == "docs_upsert":
        return await _tool_docs_upsert(args)
    if name == "docs_set_flags":
        return await _tool_docs_set_flags(args)
    if name == "docs_search":
        return await _tool_docs_search(args)
    if name == "docs_sync":
        return await _tool_docs_sync(args)
    if name == "docs_agent_run":
        return await _tool_docs_agent_run(args)
    if name == "workflow_run":
        return await _tool_workflow_run(args)
    if name == "report_pdf":
        return await _tool_report_pdf(args)
    if name == "report_ppt":
        return await _tool_report_ppt(args)
    if name == "plan_task":
        return await _tool_plan_task(args)
    if name == "run_plan":
        return await _tool_run_plan(args)
    if name == "deep_agent":
        return await _tool_deep_agent(args)
    if name == "agent_profiles_list":
        return await _tool_agent_profiles_list(args)
    if name == "chat_runtime_info":
        return await _tool_chat_runtime_info(args)
    if name == "agent_run_start":
        return await _tool_agent_run_start(args)
    if name == "agent_run_status":
        return await _tool_agent_run_status(args)
    if name == "agent_run_resume":
        return await _tool_agent_run_resume(args)
    if name == "agent_run_cancel":
        return await _tool_agent_run_cancel(args)
    if name == "agent_run_artifacts":
        return await _tool_agent_run_artifacts(args)
    if name == "sheet_apply_nl":
        return await _tool_sheet_apply_nl(args)
    if name == "wrangler_suggest":
        return await _tool_wrangler_suggest(args)

    if name == "summarize_text":
        text = await _tool_summarize_text(args)
    elif name == "chat":
        text = await _tool_chat(args)
    elif name == "echo":
        text = _tool_echo(args)
    elif name == "connector_health":
        return await _tool_connector_health(args)
    elif name == "connector_summary":
        return await _tool_connector_summary(args)
    elif name == "topology_graph":
        return await _tool_topology_graph(args)
    elif name == "architecture_graph":
        return await _tool_architecture_graph(args)
    elif name == "overview_summary":
        return await _tool_overview_summary(args)
    else:
        # Route to registered connectors dynamically
        for conn in list_connectors():
            for t in conn.tools():
                if t.get("name") == name:
                    try:
                        # Connectors return a standard {content, isError} envelope
                        return await conn.dispatch(name, args)
                    except Exception as e:  # noqa: BLE001
                        import traceback
                        tb = traceback.format_exc()
                        print(f"[connector error] name={name} args={args}\n{tb}", flush=True)
                        return {
                            "content": [{"type": "text", "text": f"[ConnectorError] {type(e).__name__}: {e}"}],
                            "isError": True,
                        }
        return {
            "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
            "isError": True,
        }
    return {"content": [{"type": "text", "text": text}], "isError": False}


def _result(rpc_id: Any, value: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rpc_id, "result": value}


def _error(rpc_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}


async def _handle_rpc(msg: dict[str, Any]) -> dict[str, Any] | None:
    method = msg.get("method")
    rpc_id = msg.get("id")
    params = msg.get("params") or {}

    if method == "initialize":
        return _result(
            rpc_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "serverInfo": SERVER_INFO,
                "capabilities": {"tools": {"listChanged": False}},
            },
        )
    if method in ("notifications/initialized", "initialized"):
        return None  # notification, no response
    if method == "ping":
        return _result(rpc_id, {})
    if method == "tools/list":
        return _result(rpc_id, {"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            payload = await _dispatch_tool(name, args)
        except (dbmod.SpecError, dbmod.ExecError) as e:
            return _result(
                rpc_id,
                {"content": [{"type": "text", "text": f"[{type(e).__name__}] {e}"}], "isError": True},
            )
        except httpx.HTTPError as e:
            return _error(rpc_id, -32000, f"Upstream error: {e}")
        except Exception as e:  # noqa: BLE001
            import traceback
            tb = traceback.format_exc()
            print(f"[mcp tool error] name={name} args={args}\n{tb}", flush=True)
            return _error(rpc_id, -32000, f"Tool error: {type(e).__name__}: {e}")
        return _result(rpc_id, payload)

    if rpc_id is None:
        return None
    return _error(rpc_id, -32601, f"Method not found: {method}")


# ---------------------------------------------------------------------------
# Session + auth + rate limit (stage 3)
# ---------------------------------------------------------------------------

import asyncio  # noqa: E402
import time as _time  # noqa: E402
import uuid  # noqa: E402

MCP_AUTH_TOKEN = os.environ.get("MCP_AUTH_TOKEN") or ""
MCP_RATE_PER_MIN = int(os.environ.get("MCP_RATE_PER_MIN", "60"))
SESSION_TTL = float(os.environ.get("MCP_SESSION_TTL", "1800"))  # 30 min idle
SESSION_HEADER = "Mcp-Session-Id"


class _Session:
    __slots__ = ("id", "last_seen", "tokens", "last_refill", "events", "event_seq", "sse_clients")

    def __init__(self, sid: str):
        self.id = sid
        self.last_seen = _time.time()
        # Token-bucket: full to start, refills at MCP_RATE_PER_MIN per 60s.
        self.tokens = float(MCP_RATE_PER_MIN)
        self.last_refill = _time.time()
        # Per-session SSE queue. JSON-RPC responses are mirrored here so
        # Streamable-HTTP clients can consume them from GET /mcp while legacy
        # clients still receive the normal synchronous POST response.
        self.events: asyncio.Queue[str] = asyncio.Queue(maxsize=100)
        self.event_seq = 0
        self.sse_clients = 0


_sessions: dict[str, _Session] = {}
_sessions_lock = asyncio.Lock()


async def _gc_sessions() -> None:
    now = _time.time()
    stale = [sid for sid, s in _sessions.items() if now - s.last_seen > SESSION_TTL]
    for sid in stale:
        _sessions.pop(sid, None)


def _refill(sess: _Session) -> None:
    now = _time.time()
    elapsed = now - sess.last_refill
    sess.tokens = min(float(MCP_RATE_PER_MIN), sess.tokens + (MCP_RATE_PER_MIN * elapsed / 60.0))
    sess.last_refill = now


def _auth_ok(request: Request) -> bool:
    if not MCP_AUTH_TOKEN:
        return True
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return False
    return auth[len("Bearer "):].strip() == MCP_AUTH_TOKEN


def _unauthorized() -> JSONResponse:
    return JSONResponse(
        _error(None, -32001, "Unauthorized"),
        status_code=401,
        headers={"WWW-Authenticate": 'Bearer realm="mcp"'},
    )


def _too_many() -> JSONResponse:
    return JSONResponse(_error(None, -32002, "Rate limit exceeded"), status_code=429)


def _wants_sse_post_response(request: Request) -> bool:
    """Opt-in async response routing for clients with an open GET /mcp stream."""
    prefer = request.headers.get("Prefer", "").lower()
    mode = request.headers.get("X-MCP-Response-Mode", "").lower()
    return "respond-async" in prefer or mode == "sse"


def _sse(event: str, data: str, event_id: int | None = None) -> str:
    # Split data lines per SSE framing rules. JSON payloads are normally one
    # line, but this keeps the function correct for any future pretty payload.
    prefix = f"id: {event_id}\n" if event_id is not None else ""
    lines = "\n".join(f"data: {line}" for line in data.splitlines() or [""])
    return f"{prefix}event: {event}\n{lines}\n\n"


async def _enqueue_sse_response(sess: _Session, payload: Any, *, force: bool = False) -> None:
    if not force and sess.sse_clients < 1:
        return
    sess.event_seq += 1
    event = _sse("message", json.dumps(payload, separators=(",", ":")), sess.event_seq)
    if sess.events.full():
        try:
            sess.events.get_nowait()
        except asyncio.QueueEmpty:
            pass
    await sess.events.put(event)


app = FastAPI(title="sglandsimple MCP server")


@app.on_event("startup")
async def _startup_log() -> None:
    await init_connectors()
    if not MCP_AUTH_TOKEN:
        print(
            "[mcp] WARNING: MCP_AUTH_TOKEN is not set; /mcp is open. "
            "Set MCP_AUTH_TOKEN in .env.local to require bearer auth.",
            flush=True,
        )
    else:
        print(f"[mcp] bearer auth enabled (token length {len(MCP_AUTH_TOKEN)})", flush=True)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/mcp")
async def mcp_post(request: Request) -> Response:
    if not _auth_ok(request):
        return _unauthorized()

    body = await request.body()
    try:
        msg = json.loads(body)
    except json.JSONDecodeError:
        return JSONResponse(_error(None, -32700, "Parse error"), status_code=400)

    # initialize is the only method that may arrive without a session id —
    # the response carries a freshly-minted one.
    is_initialize = (
        isinstance(msg, dict) and msg.get("method") == "initialize"
    )
    incoming_sid = request.headers.get(SESSION_HEADER)
    response_headers: dict[str, str] = {}

    async with _sessions_lock:
        await _gc_sessions()
        if is_initialize:
            sid = incoming_sid or str(uuid.uuid4())
            sess = _sessions.setdefault(sid, _Session(sid))
            sess.last_seen = _time.time()
            response_headers[SESSION_HEADER] = sid
        else:
            if not incoming_sid:
                # Lenient mode: if no sessions exist yet, allow the first
                # non-initialize request (legacy clients, our own agent).
                if not _sessions:
                    sid = str(uuid.uuid4())
                    sess = _sessions.setdefault(sid, _Session(sid))
                    response_headers[SESSION_HEADER] = sid
                else:
                    return JSONResponse(
                        _error(None, -32003, f"Missing {SESSION_HEADER} header"),
                        status_code=400,
                    )
            else:
                sess = _sessions.get(incoming_sid)
                if sess is None:
                    return JSONResponse(
                        _error(None, -32004, "Unknown or expired session"),
                        status_code=400,
                    )
                sess.last_seen = _time.time()

        # Rate limit: one token per request (batched JSON-RPC = one token).
        _refill(sess)
        if sess.tokens < 1.0:
            return _too_many()
        sess.tokens -= 1.0

    wants_sse = _wants_sse_post_response(request)

    if isinstance(msg, list):
        responses = [r for r in [await _handle_rpc(m) for m in msg] if r is not None]
        if not responses:
            return Response(status_code=202, headers=response_headers)
        await _enqueue_sse_response(sess, responses, force=wants_sse)
        if wants_sse:
            return Response(status_code=202, headers=response_headers)
        return JSONResponse(responses, headers=response_headers)

    resp = await _handle_rpc(msg)
    if resp is None:
        return Response(status_code=202, headers=response_headers)
    await _enqueue_sse_response(sess, resp, force=wants_sse)
    if wants_sse:
        return Response(status_code=202, headers=response_headers)
    return JSONResponse(resp, headers=response_headers)


@app.get("/mcp")
async def mcp_get(request: Request) -> Response:
    if not _auth_ok(request):
        return _unauthorized()

    incoming_sid = request.headers.get(SESSION_HEADER)
    response_headers: dict[str, str] = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }

    async with _sessions_lock:
        await _gc_sessions()
        if not incoming_sid:
            # Lenient keepalive mode for older probes that just expect GET
            # /mcp to be an SSE endpoint. They receive pings only until they
            # initialize and reconnect with Mcp-Session-Id.
            sid = str(uuid.uuid4())
            sess = _sessions.setdefault(sid, _Session(sid))
            response_headers[SESSION_HEADER] = sid
        else:
            sess = _sessions.get(incoming_sid)
            if sess is None:
                return JSONResponse(
                    _error(None, -32004, "Unknown or expired session"),
                    status_code=400,
                )
            sess.last_seen = _time.time()
            response_headers[SESSION_HEADER] = sess.id

    async def event_stream():
        sess.sse_clients += 1
        try:
            sess.event_seq += 1
            yield _sse("ready", json.dumps({"sessionId": sess.id}), sess.event_seq)
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(sess.events.get(), timeout=15)
                    sess.last_seen = _time.time()
                    yield event
                except asyncio.TimeoutError:
                    sess.event_seq += 1
                    sess.last_seen = _time.time()
                    yield _sse("ping", "{}", sess.event_seq)
        finally:
            sess.sse_clients = max(0, sess.sse_clients - 1)

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=response_headers)
