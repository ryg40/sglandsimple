"""Per-LLM-call token budget for the deep-agent subagents.

Uses tiktoken's ``cl100k_base`` encoding for the estimate (cheap, no
network). If tiktoken can't load — offline build, missing data file —
fall back to a coarse `len(text) // 4` estimate so the system stays
functional and the budget guard still triggers on large inputs.
"""

from __future__ import annotations

import os
import sys

_BUDGET = int(os.environ.get("DEEP_AGENT_BUDGET_PER_CALL", "70000"))
_ENC = None
_ENC_TRIED = False


def _enc():
    global _ENC, _ENC_TRIED
    if _ENC_TRIED:
        return _ENC
    _ENC_TRIED = True
    try:
        import tiktoken  # type: ignore

        _ENC = tiktoken.get_encoding("cl100k_base")
    except Exception as e:  # noqa: BLE001
        print(f"[deep_agent.budget] tiktoken unavailable, using len/4 fallback: {e}", file=sys.stderr, flush=True)
        _ENC = None
    return _ENC


def token_count_estimate(text: str) -> int:
    if not text:
        return 0
    enc = _enc()
    if enc is None:
        return max(1, len(text) // 4)
    return len(enc.encode(text))


def budget_limit() -> int:
    return _BUDGET


def log_event(role: str, kind: str, tokens: int, **extra) -> None:
    """Single-line structured log for budget events."""
    bits = [f"role={role}", f"kind={kind}", f"tokens={tokens}", f"budget={_BUDGET}"]
    for k, v in extra.items():
        bits.append(f"{k}={v}")
    print("[deep_agent.budget] " + " ".join(bits), flush=True)
