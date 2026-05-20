"""Single seam between LangGraph nodes and the upstream OpenAI-compatible LLM.

- ``chat_model()`` returns a ``ChatOpenAI`` for nodes that just want plain
  text replies.
- ``structured(schema, system, user)`` runs one constrained-JSON call and
  returns a typed Pydantic instance.

The structured helper deliberately bypasses ``ChatOpenAI.with_structured_output``
and uses the OpenAI ``response_format`` parameter directly. The upstream
we target enforces ``json_schema`` server-side and returns clean JSON;
the langchain wrappers add wrappers (``json_object`` + manual parsing,
function-calling, etc.) that interact poorly with some models'
tool-call output formats and produce parse errors on otherwise valid
outputs.
"""

from __future__ import annotations

import json
import os
from typing import TypeVar

from langchain_openai import ChatOpenAI
from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} environment variable is required")
    return value


UPSTREAM_BASE_URL = _required_env("UPSTREAM_BASE_URL")
UPSTREAM_API_KEY = os.environ.get("UPSTREAM_API_KEY", "dummy")
UPSTREAM_MODEL = _required_env("UPSTREAM_MODEL")

_oai: AsyncOpenAI | None = None


def _client() -> AsyncOpenAI:
    global _oai
    if _oai is None:
        _oai = AsyncOpenAI(base_url=UPSTREAM_BASE_URL, api_key=UPSTREAM_API_KEY)
    return _oai


def chat_model(temperature: float = 0.2) -> ChatOpenAI:
    return ChatOpenAI(
        base_url=UPSTREAM_BASE_URL,
        api_key=UPSTREAM_API_KEY,
        model=UPSTREAM_MODEL,
        temperature=temperature,
    )


T = TypeVar("T", bound=BaseModel)


def _strip_fences(text: str) -> str:
    """If the model wrapped JSON in a ```json fence, extract the JSON."""
    t = text.strip()
    if t.startswith("```"):
        # Drop the opening fence (with optional language) and the trailing fence.
        first_nl = t.find("\n")
        if first_nl != -1:
            t = t[first_nl + 1 :]
        if t.endswith("```"):
            t = t[: -3]
    return t.strip()


def _model_schema(schema: type[BaseModel]) -> dict:
    """Pydantic JSON-schema for a model, normalized for OpenAI response_format.strict."""
    s = schema.model_json_schema()
    # OpenAI strict mode requires additionalProperties:false on every object schema.
    def _fix(node):
        if isinstance(node, dict):
            if node.get("type") == "object" and "additionalProperties" not in node:
                node["additionalProperties"] = False
            for v in node.values():
                _fix(v)
        elif isinstance(node, list):
            for v in node:
                _fix(v)
    _fix(s)
    return s


def _extract_json(text: str) -> str | None:
    """Best-effort: pull a JSON object out of a freeform string."""
    t = _strip_fences(text)
    # Already pure JSON?
    if t.startswith("{") and t.endswith("}"):
        return t
    # Find the first '{' and the matching closing '}'.
    depth = 0
    start = -1
    for i, ch in enumerate(t):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start != -1:
                return t[start : i + 1]
    return None


# Qwen3 emits a long "reasoning" trace before the actual answer when
# enable_thinking=True (the default on many deployments). For
# constrained-JSON calls and tool selection we want the model to answer
# immediately. Toggle via extra_body so we don't depend on a specific
# SDK feature for it.
EXTRA_BODY = {"chat_template_kwargs": {"enable_thinking": False}}


async def _call_once(schema: type[T], system: str, user: str, temperature: float, use_schema: bool) -> str:
    cli = _client()
    if use_schema:
        rf = {
            "type": "json_schema",
            "json_schema": {
                "name": schema.__name__,
                "schema": _model_schema(schema),
                "strict": True,
            },
        }
    else:
        rf = {"type": "json_object"}
    r = await cli.chat.completions.create(
        model=UPSTREAM_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        response_format=rf,
        extra_body=EXTRA_BODY,
    )
    return r.choices[0].message.content or ""


async def structured(schema: type[T], system: str, user: str, temperature: float = 0.2) -> T:
    """Run one constrained-JSON call. Returns an instance of `schema`.

    Tries ``response_format={"type": "json_schema", "strict": true}`` first.
    Some upstreams (notably vLLM/SGLang behind certain Qwen3 templates)
    silently ignore it and return prose; fall back to ``json_object`` mode
    with the schema in the system prompt, and as a last resort try to
    locate a JSON object inside the response text.
    """
    schema_obj = _model_schema(schema)
    schema_hint = (
        "\n\nReturn ONLY a JSON object matching this schema (no prose, no "
        "code fences):\n" + json.dumps(schema_obj)
    )

    attempts = [
        (system, True),
        (system + schema_hint, False),
        (system + schema_hint, True),
    ]

    last_raw = ""
    last_err: Exception | None = None
    for sys_prompt, use_schema in attempts:
        try:
            raw = await _call_once(schema, sys_prompt, user, temperature, use_schema)
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue
        last_raw = raw
        candidate = _extract_json(raw)
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        try:
            return schema.model_validate(data)
        except ValidationError as e:
            last_err = e
            continue

    raise RuntimeError(
        f"structured(): no attempt produced a valid {schema.__name__}. "
        f"Last raw={last_raw!r}; last error={last_err}"
    )
