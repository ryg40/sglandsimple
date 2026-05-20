"""Single seam between LangGraph nodes and the upstream OpenAI-compatible LLM.

Two helpers:

- `chat_model()` returns a configured `ChatOpenAI` for nodes that just
  want plain text or tool calls.
- `structured(schema, system, user)` runs one constrained-JSON call and
  returns a typed Pydantic instance — this is the path used by
  `plan_query` and `synthesize` in the ask_data graph.
"""

from __future__ import annotations

import os
from typing import TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} environment variable is required")
    return value


def chat_model(temperature: float = 0.2) -> ChatOpenAI:
    return ChatOpenAI(
        base_url=_required_env("UPSTREAM_BASE_URL"),
        api_key=os.environ.get("UPSTREAM_API_KEY", "dummy"),
        model=_required_env("UPSTREAM_MODEL"),
        temperature=temperature,
    )


T = TypeVar("T", bound=BaseModel)


async def structured(schema: type[T], system: str, user: str, temperature: float = 0.2) -> T:
    """Run one constrained-JSON call. Returns an instance of `schema`."""
    model = chat_model(temperature=temperature).with_structured_output(
        schema, method="json_schema", strict=True
    )
    return await model.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
