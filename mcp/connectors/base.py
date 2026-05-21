"""Connector protocol definition for Stage 9 external system integrations."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Connector(Protocol):
    """Every Stage 9 connector exposes health, summary, and MCP tools."""

    name: str

    async def health(self) -> dict:
        """Return a small status dict. Must not raise when disabled."""
        ...

    async def summary(self) -> dict:
        """Return one-line metric summary. Must not raise when disabled."""
        ...

    def tools(self) -> list[dict]:
        """Return a list of MCP tool definitions for this connector."""
        ...
