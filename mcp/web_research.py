"""Web research workflow expressed as a LangGraph StateGraph.

Flow:

    START → search → fan_out_annotate → annotate_one (parallel via Send)
          → synthesize (structured) → END

The constrained-JSON output schema is the same one the previous SGLang
implementation produced — both Markdown and JSON renderings are returned
to the MCP caller.
"""

from __future__ import annotations

import operator
import os
from dataclasses import dataclass
from typing import Annotated, Any

import httpx
from langgraph.constants import Send
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from llm import structured


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} environment variable is required")
    return value


SEARXNG_URL = _required_env("SEARXNG_URL").rstrip("/")
SEARCH_TIMEOUT = float(os.environ.get("SEARXNG_TIMEOUT", "20"))
MIN_RESULTS = int(os.environ.get("WEB_RESEARCH_MIN_RESULTS", "5"))


@dataclass
class SearchHit:
    index: int
    title: str
    url: str
    snippet: str
    relevance_note: str = ""


# ---------------------------------------------------------------------------
# Search
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
# LangGraph state + IO models
# ---------------------------------------------------------------------------


class RelevanceNote(BaseModel):
    index: int
    note: str


class BestResult(BaseModel):
    index: int = Field(ge=1)
    url: str
    quote: str
    why: str


class Citation(BaseModel):
    index: int = Field(ge=1)
    title: str
    url: str


class WebResearchFinal(BaseModel):
    topic: str
    summary: str
    best_result: BestResult
    citations: list[Citation] = Field(min_length=1)


class WebState(BaseModel):
    topic: str
    k: int
    hits: list[dict[str, Any]] = Field(default_factory=list)
    notes: Annotated[list[RelevanceNote], operator.add] = Field(default_factory=list)
    final: WebResearchFinal | None = None


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


async def node_search(state: WebState) -> dict[str, Any]:
    hits = await searxng_search(state.topic, state.k)
    return {"hits": [h.__dict__ for h in hits]}


def node_fan_out_annotate(state: WebState) -> list[Send]:
    return [
        Send("annotate_one", {"topic": state.topic, "hit": h})
        for h in state.hits
    ]


ANNOTATE_SYSTEM = """\
You are a research assistant. In one sentence, explain how the given search
result relates to the topic. Do not invent facts beyond what the title and
snippet support. Return JSON {"index": <int>, "note": "<one sentence>"}.
"""


async def node_annotate_one(payload: dict[str, Any]) -> dict[str, Any]:
    hit = payload["hit"]
    topic = payload["topic"]
    user = (
        f"Topic: {topic}\n"
        f"Result index: {hit['index']}\n"
        f"Title: {hit['title']}\n"
        f"URL: {hit['url']}\n"
        f"Snippet: {hit['snippet']}"
    )
    note = await structured(RelevanceNote, ANNOTATE_SYSTEM, user)
    # Force index match.
    return {"notes": [RelevanceNote(index=int(hit["index"]), note=note.note)]}


SYNTH_SYSTEM = """\
You are a careful research analyst. Given a topic and numbered search
results, produce a final synthesis. Rules:

- summary must contain at least one sentence and every factual claim ends
  with one or more bracketed markers like [1] or [2,3] keyed to citations.
- best_result.quote MUST be a verbatim substring of that result's snippet.
- best_result.url MUST equal the URL of the chosen result.
- citations must list every index referenced in summary, with the title
  and URL from the matching numbered result.
- Do not invent URLs.
"""


async def node_synthesize(state: WebState) -> dict[str, Any]:
    # Stitch hits + notes for the prompt.
    notes_by_index = {n.index: n.note for n in state.notes}
    bulleted = "\n".join(
        f"[{h['index']}] {h['title']}\n    URL: {h['url']}\n    Snippet: {h['snippet']}\n"
        f"    Note: {notes_by_index.get(h['index'], '')}"
        for h in state.hits
    )
    user = f"Topic: {state.topic}\n\nSearch results:\n{bulleted}"
    final = await structured(WebResearchFinal, SYNTH_SYSTEM, user)
    # Ensure topic echoed correctly.
    final = final.model_copy(update={"topic": state.topic})
    return {"final": final}


# ---------------------------------------------------------------------------
# Build graph
# ---------------------------------------------------------------------------


def build_graph():
    g = StateGraph(WebState)
    g.add_node("search", node_search)
    g.add_node("fan_out_annotate", lambda s: {})
    g.add_node("annotate_one", node_annotate_one)
    g.add_node("synthesize", node_synthesize)

    g.add_edge(START, "search")
    g.add_edge("search", "fan_out_annotate")
    g.add_conditional_edges("fan_out_annotate", node_fan_out_annotate, ["annotate_one"])
    g.add_edge("annotate_one", "synthesize")
    g.add_edge("synthesize", END)

    return g.compile()


_GRAPH = None


def _get_graph():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    return _GRAPH


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


async def run_web_research(topic: str, k: int = MIN_RESULTS) -> dict[str, Any]:
    k = max(k, MIN_RESULTS)
    graph = _get_graph()
    out = await graph.ainvoke({"topic": topic, "k": k})
    state = WebState.model_validate(out)
    assert state.final is not None
    payload = state.final.model_dump()
    notes_by_index = {n.index: n.note for n in state.notes}
    payload["results"] = [
        {
            "index": h["index"],
            "title": h["title"],
            "url": h["url"],
            "snippet": h["snippet"],
            "note": notes_by_index.get(h["index"], ""),
        }
        for h in state.hits
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
