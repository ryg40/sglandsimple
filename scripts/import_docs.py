#!/usr/bin/env python3
"""Stage 14 — Import existing Markdown corpus into the Docs Wiki.

Walks root *.md files and docs/*.md in the repo, calling docs_upsert for each
via MCP JSON-RPC over HTTP.  Idempotent: re-running upserts the same slugs
without creating duplicates (docs_upsert is by-slug).

Usage:
    python3 scripts/import_docs.py [--dry-run] [--repo-root PATH]

Env:
    MCP_URL          MCP server base URL (default: http://localhost:5451/mcp)
    MCP_AUTH_TOKEN   Bearer token if the MCP server requires auth (optional)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
import urllib.error
from pathlib import Path

MCP_URL = os.environ.get("MCP_URL", "http://localhost:5451/mcp")
MCP_AUTH_TOKEN = os.environ.get("MCP_AUTH_TOKEN", "")

# ---------------------------------------------------------------------------
# MCP JSON-RPC client (stdlib only, no httpx dependency at import time)
# ---------------------------------------------------------------------------

_session_id: str | None = None
_rpc_id = 0


def _next_id() -> int:
    global _rpc_id
    _rpc_id += 1
    return _rpc_id


def _headers() -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    if MCP_AUTH_TOKEN:
        h["Authorization"] = f"Bearer {MCP_AUTH_TOKEN}"
    if _session_id:
        h["Mcp-Session-Id"] = _session_id
    return h


def _rpc_raw(body: dict) -> tuple[dict, dict[str, str]]:
    """Send one JSON-RPC request and return (response_body, response_headers)."""
    data = json.dumps(body).encode()
    req = urllib.request.Request(MCP_URL, data=data, headers=_headers(), method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp_headers = dict(resp.getheaders())
        resp_body = json.loads(resp.read())
    return resp_body, resp_headers


def _initialize() -> None:
    global _session_id
    body = {
        "jsonrpc": "2.0",
        "id": _next_id(),
        "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
    }
    _, headers = _rpc_raw(body)
    sid = headers.get("Mcp-Session-Id") or headers.get("mcp-session-id")
    if sid:
        _session_id = sid


def _tool_call(name: str, arguments: dict) -> dict:
    """Call an MCP tool and return the result envelope {content, isError}."""
    global _session_id
    if _session_id is None:
        _initialize()
    body = {
        "jsonrpc": "2.0",
        "id": _next_id(),
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }
    resp, _ = _rpc_raw(body)
    if "error" in resp:
        raise RuntimeError(f"MCP error: {resp['error']}")
    return resp.get("result", {})


# ---------------------------------------------------------------------------
# Markdown metadata helpers
# ---------------------------------------------------------------------------


def _extract_title(body: str, filename: str) -> str:
    """Return the text of the first H1, or title-case the filename stem."""
    m = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
    if m:
        return m.group(1).strip()
    return filename.replace("-", " ").replace("_", " ").title()


def _path_to_slug(path_str: str) -> str:
    """
    docs/clients.md → slug=clients, path=docs/clients
    README.md       → slug=readme, path=README
    IMPLEMENT.md    → slug=implement, path=IMPLEMENT
    WAVE1.md        → slug=wave1, path=WAVE1
    """
    p = Path(path_str)
    stem = p.stem.lower().replace(" ", "-")
    return stem


def _path_to_wiki_path(path_str: str) -> str:
    """Return the slug path (without extension) as used in the wiki path field."""
    p = Path(path_str)
    if p.parent == Path("."):
        return p.stem  # root file → bare stem
    return str(p.parent / p.stem)


def _infer_tags(wiki_path: str, filename: str) -> list[str]:
    """Derive default tags from the path and filename."""
    tags: list[str] = []
    parts = wiki_path.lower().replace("\\", "/").split("/")
    if len(parts) > 1:
        tags.append(parts[0])  # leading dir as a tag
    stem = Path(filename).stem.lower()
    if stem.startswith("wave"):
        tags.append("changelog")
    elif stem in ("readme",):
        tags.append("overview")
    elif stem in ("implement",):
        tags.append("backlog")
    elif stem in ("claude",):
        tags.append("developer")
    elif stem in ("plantmux", "progress"):
        tags.append("internal")
    elif "client" in stem:
        tags.append("clients")
    elif "deep_agent" in stem or "agent" in stem:
        tags.append("agent")
    if not tags:
        tags.append("documentation")
    return list(dict.fromkeys(tags))  # dedup, preserve order


# ---------------------------------------------------------------------------
# Corpus discovery
# ---------------------------------------------------------------------------


def discover_docs(repo_root: Path) -> list[dict[str, str]]:
    """Return a list of {abs_path, rel_path, slug, wiki_path, title_hint, tags} dicts."""
    candidates: list[Path] = []

    # Root *.md files (exclude node_modules, dist, .git, web/ subtree)
    skip_dirs = {"node_modules", "dist", ".git", "web", "sandbox"}
    for p in repo_root.glob("*.md"):
        candidates.append(p)
    # docs/*.md
    docs_dir = repo_root / "docs"
    if docs_dir.is_dir():
        for p in docs_dir.glob("*.md"):
            candidates.append(p)
    # scripts/*.md
    scripts_dir = repo_root / "scripts"
    if scripts_dir.is_dir():
        for p in scripts_dir.glob("*.md"):
            candidates.append(p)

    out: list[dict[str, str]] = []
    for p in sorted(candidates):
        rel = str(p.relative_to(repo_root))
        slug = _path_to_slug(rel)
        wiki_path = _path_to_wiki_path(rel)
        out.append(
            {
                "abs_path": str(p),
                "rel_path": rel,
                "slug": slug,
                "wiki_path": wiki_path,
                "filename": p.name,
            }
        )
    return out


# ---------------------------------------------------------------------------
# Import logic
# ---------------------------------------------------------------------------


def import_doc(entry: dict[str, str], *, dry_run: bool) -> dict:
    body = Path(entry["abs_path"]).read_text(encoding="utf-8", errors="replace")
    title = _extract_title(body, entry["filename"])
    tags = _infer_tags(entry["wiki_path"], entry["filename"])

    print(
        f"  {'[DRY-RUN] ' if dry_run else ''}upsert slug={entry['slug']!r:20} "
        f"path={entry['wiki_path']!r:30} title={title!r:.50}"
    )

    if dry_run:
        return {
            "slug": entry["slug"],
            "path": entry["wiki_path"],
            "title": title,
            "tags": tags,
            "skipped": True,
        }

    args = {
        "slug": entry["slug"],
        "path": entry["wiki_path"],
        "title": title,
        "body_md": body,
        "tags": tags,
        "status": "up_to_date",
        "visibility": "internal",
        "owner": "import_docs.py",
        "note": f"Imported from {entry['rel_path']} by import_docs.py",
    }
    result = _tool_call("docs_upsert", args)
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Import repo Markdown corpus into the Docs Wiki.")
    parser.add_argument("--dry-run", action="store_true", help="List what would be imported without writing.")
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).parent.parent),
        help="Repository root (default: parent of scripts/ dir).",
    )
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    print(f"Repository root : {repo_root}")
    print(f"MCP URL         : {MCP_URL}")
    print(f"Dry-run         : {args.dry_run}")
    print()

    docs = discover_docs(repo_root)
    if not docs:
        print("No Markdown files found.")
        return 0

    print(f"Found {len(docs)} Markdown file(s):\n")

    if not args.dry_run:
        try:
            _initialize()
        except Exception as e:
            print(f"ERROR: Cannot reach MCP server at {MCP_URL}: {e}", file=sys.stderr)
            print("Re-run with --dry-run to preview the import plan, or ensure the stack is running.", file=sys.stderr)
            return 1

    ok = 0
    failed = 0
    for entry in docs:
        try:
            import_doc(entry, dry_run=args.dry_run)
            ok += 1
        except Exception as e:
            print(f"  ERROR upsert {entry['slug']}: {e}", file=sys.stderr)
            failed += 1

    print()
    if args.dry_run:
        print(f"Dry-run complete — {ok} doc(s) would be imported.")
    else:
        print(f"Import complete — {ok} succeeded, {failed} failed.")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
