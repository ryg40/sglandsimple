"""Web research workflow expressed with the SGLang frontend DSL.

Pedagogical notes (why this code looks the way it does):

* `sgl.function` defines a *program* over an LLM. The `s` parameter is the
  generation state — `s += "..."` appends to the prompt; `s += sgl.gen(name)`
  asks the backend to generate a value bound to `name`. The whole function
  becomes one logical session against the backend.

* `sgl.fork(N)` creates N independent child states branching off the current
  prompt. Each child runs in parallel against the backend. On SGLang's native
  runtime this exploits RadixAttention (shared KV prefix); against a remote
  OpenAI endpoint it degrades to N concurrent HTTP calls — same API, fewer
  wins. We use it here to extract per-result relevance notes concurrently.

* `sgl.OpenAI(model)` configures the OpenAI-compatible backend. We set it
  globally with `sgl.set_default_backend(...)`. The SGLang client honors
  `OPENAI_BASE_URL` / `OPENAI_API_KEY` env vars.

* For the final structured payload we bypass the DSL and call the OpenAI
  client directly with `response_format={"type": "json_schema", ...}`. This
  is the *real* SGLang/vLLM constrained-decoding feature, and it gives us a
  guaranteed-shape JSON object — far more reliable than asking the model
  nicely and then `json.loads`-ing the reply.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any

import httpx
import sglang as sgl
from openai import AsyncOpenAI

def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} environment variable is required")
    return value


UPSTREAM_BASE_URL = _required_env("UPSTREAM_BASE_URL")
UPSTREAM_API_KEY = os.environ.get("UPSTREAM_API_KEY", "dummy")
UPSTREAM_MODEL = _required_env("UPSTREAM_MODEL")

SEARXNG_URL = _required_env("SEARXNG_URL").rstrip("/")
SEARCH_TIMEOUT = float(os.environ.get("SEARXNG_TIMEOUT", "20"))
MIN_RESULTS = int(os.environ.get("WEB_RESEARCH_MIN_RESULTS", "5"))

# Configure the SGLang frontend to talk to the remote OpenAI-compatible server.
# Setting these env vars before constructing the backend is the documented path.
os.environ.setdefault("OPENAI_BASE_URL", UPSTREAM_BASE_URL)
os.environ.setdefault("OPENAI_API_KEY", UPSTREAM_API_KEY)
sgl.set_default_backend(sgl.OpenAI(UPSTREAM_MODEL))

# Reused for the constrained-JSON final step.
_oai = AsyncOpenAI(base_url=UPSTREAM_BASE_URL, api_key=UPSTREAM_API_KEY)


@dataclass
class SearchHit:
    index: int  # 1-based citation index
    title: str
    url: str
    snippet: str
    relevance_note: str = ""  # filled in by the fork stage


# ---------------------------------------------------------------------------
# 1. Search
# ---------------------------------------------------------------------------


async def searxng_search(query: str, k: int) -> list[SearchHit]:
    params = {"q": query, "format": "json", "safesearch": "0"}
    async with httpx.AsyncClient(timeout=SEARCH_TIMEOUT) as client:
        r = await client.get(f"{SEARXNG_URL}/search", params=params)
        r.raise_for_status()
        data = r.json()
    raw = data.get("results", [])
    hits: list[SearchHit] = []
    seen_urls: set[str] = set()
    for item in raw:
        url = (item.get("url") or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        hits.append(
            SearchHit(
                index=len(hits) + 1,
                title=(item.get("title") or "").strip() or url,
                url=url,
                snippet=(item.get("content") or "").strip(),
            )
        )
        if len(hits) >= k:
            break
    if len(hits) < MIN_RESULTS:
        raise RuntimeError(
            f"SearXNG returned only {len(hits)} usable results for {query!r}; need at least {MIN_RESULTS}"
        )
    return hits


# ---------------------------------------------------------------------------
# 2. SGLang program — per-result relevance notes via fork
# ---------------------------------------------------------------------------


@sgl.function
def annotate_relevance(s, topic: str, hit: dict):
    """Produce a one-sentence note explaining how a single result relates to the topic."""
    s += sgl.system(
        "You are a research assistant. In one sentence, explain how the given search "
        "result relates to the topic. Do not invent facts beyond what the title and "
        "snippet support. No preamble."
    )
    s += sgl.user(
        f"Topic: {topic}\n"
        f"Result title: {hit['title']}\n"
        f"Result URL: {hit['url']}\n"
        f"Snippet: {hit['snippet']}"
    )
    s += sgl.assistant(sgl.gen("note", max_tokens=120, temperature=0.2))


@sgl.function
def annotate_all(s, topic: str, hits: list[dict]):
    """Fan out: one fork per hit, each running annotate_relevance in parallel."""
    forks = s.fork(len(hits))
    for child, hit in zip(forks, hits):
        child += annotate_relevance.run(topic=topic, hit=hit)
    forks.join()
    # Collect the notes back into the parent state's metadata.
    s["notes"] = [child["note"].strip() for child in forks]


# ---------------------------------------------------------------------------
# 3. Final summary via constrained-JSON decoding
# ---------------------------------------------------------------------------

FINAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["topic", "summary", "best_result", "citations"],
    "properties": {
        "topic": {"type": "string"},
        "summary": {
            "type": "string",
            "description": (
                "A multi-sentence synthesis of what the search results say about the topic. "
                "Every factual claim must be followed by one or more bracketed citation "
                "markers like [1] or [2,3] referring to the citations array."
            ),
        },
        "best_result": {
            "type": "object",
            "additionalProperties": False,
            "required": ["index", "url", "quote", "why"],
            "properties": {
                "index": {"type": "integer", "minimum": 1},
                "url": {"type": "string"},
                "quote": {
                    "type": "string",
                    "description": "A short verbatim quote drawn from the best result's snippet.",
                },
                "why": {"type": "string", "description": "One sentence on why this is the best result."},
            },
        },
        "citations": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["index", "title", "url"],
                "properties": {
                    "index": {"type": "integer", "minimum": 1},
                    "title": {"type": "string"},
                    "url": {"type": "string"},
                },
            },
        },
    },
}


async def generate_final(topic: str, hits: list[SearchHit]) -> dict[str, Any]:
    bulleted = "\n".join(
        f"[{h.index}] {h.title}\n    URL: {h.url}\n    Snippet: {h.snippet}\n    Note: {h.relevance_note}"
        for h in hits
    )
    system = (
        "You are a careful research analyst. Given the topic and numbered search results, "
        "produce a JSON object matching the provided schema. Rules:\n"
        "- Cite every factual claim in `summary` with bracketed indices matching the citations list.\n"
        "- `best_result.quote` MUST be copied verbatim from that result's snippet.\n"
        "- `citations` must include every index you reference in `summary`.\n"
        "- Do not invent URLs; reuse only the URLs given."
    )
    user = f"Topic: {topic}\n\nSearch results:\n{bulleted}"
    resp = await _oai.chat.completions.create(
        model=UPSTREAM_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.2,
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "web_research", "schema": FINAL_SCHEMA, "strict": True},
        },
    )
    return json.loads(resp.choices[0].message.content)


# ---------------------------------------------------------------------------
# 4. Public entrypoint — used by the MCP tool
# ---------------------------------------------------------------------------


async def run_web_research(topic: str, k: int = MIN_RESULTS) -> dict[str, Any]:
    k = max(k, MIN_RESULTS)
    hits = await searxng_search(topic, k)

    # SGLang programs are synchronous; run the fork stage off the event loop.
    state = await asyncio.to_thread(
        annotate_all.run, topic=topic, hits=[h.__dict__ for h in hits]
    )
    notes = state["notes"]
    for h, note in zip(hits, notes):
        h.relevance_note = note

    payload = await generate_final(topic, hits)
    payload["results"] = [
        {"index": h.index, "title": h.title, "url": h.url, "snippet": h.snippet, "note": h.relevance_note}
        for h in hits
    ]
    return payload


def render_markdown(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"# Web research: {payload['topic']}")
    lines.append("")
    lines.append("## Summary")
    lines.append(payload["summary"])
    lines.append("")
    best = payload["best_result"]
    lines.append("## Best result")
    lines.append(f"**[{best['index']}]** <{best['url']}>")
    lines.append("")
    lines.append(f"> {best['quote']}")
    lines.append("")
    lines.append(best["why"])
    lines.append("")
    lines.append("## Citations")
    for c in payload["citations"]:
        lines.append(f"- [{c['index']}] [{c['title']}]({c['url']})")
    lines.append("")
    lines.append("## All results")
    for r in payload.get("results", []):
        lines.append(f"- [{r['index']}] [{r['title']}]({r['url']}) — {r['note']}")
    return "\n".join(lines)
