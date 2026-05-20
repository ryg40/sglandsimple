"""Live MCP tool catalog visible to the deep-agent subagents.

The planner is shown a compact catalog (name + description + input
schema) so it can pick valid tools. The builder is given a focused
subset per step. Catalog is resolved at call time so any newly
registered tool is immediately visible.

Some tools are excluded so the planner can't trigger recursion:

- ``plan_task``, ``run_plan``, ``deep_agent`` — that would re-enter the
  subagent system from inside a plan.
- ``chat``, ``summarize_text`` — too vague to be useful as steps; the
  builder LLM handles freeform generation directly.
"""

from __future__ import annotations

import json
from typing import Any

_EXCLUDED = {"plan_task", "run_plan", "deep_agent", "chat", "summarize_text", "echo"}


def _get_tools() -> list[dict[str, Any]]:
    # Late import to avoid circular dependency with server.py.
    import server  # type: ignore

    return [t for t in server.TOOLS if t.get("name") not in _EXCLUDED]


def tool_names() -> set[str]:
    return {t["name"] for t in _get_tools()}


def catalog_markdown() -> str:
    out: list[str] = []
    for t in _get_tools():
        name = t["name"]
        desc = t.get("description", "")
        schema = t.get("inputSchema") or {}
        props = schema.get("properties") or {}
        required = schema.get("required") or []
        arg_lines = []
        for arg_name, arg_schema in props.items():
            req_marker = " (required)" if arg_name in required else ""
            arg_desc = arg_schema.get("description") or arg_schema.get("type", "")
            arg_lines.append(f"  - {arg_name}{req_marker}: {arg_desc}")
        block = f"## {name}\n{desc}\nargs:\n" + ("\n".join(arg_lines) or "  (none)")
        out.append(block)
    return "\n\n".join(out)


def focused_catalog_markdown(names: list[str]) -> str:
    keep = set(names)
    blocks: list[str] = []
    for t in _get_tools():
        if t["name"] not in keep:
            continue
        blocks.append(
            f"## {t['name']}\n{t.get('description', '')}\nschema:\n```json\n"
            + json.dumps(t.get("inputSchema") or {}, indent=2)
            + "\n```"
        )
    return "\n\n".join(blocks)
