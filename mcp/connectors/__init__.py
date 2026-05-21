"""Connector registry and lifecycle management."""

from __future__ import annotations

import os
from typing import Any

from .base import Connector
from .mongodb import MongoDbConnector

_registry: dict[str, Connector] = {}

# Map env-var prefix -> connector class
_CONNECTOR_CLASSES: dict[str, type[Connector]] = {
    "MONGODB": MongoDbConnector,
}


async def init_connectors() -> None:
    """Instantiate every connector whose CONN_*_ENABLED flag is present."""
    global _registry
    for prefix, cls in _CONNECTOR_CLASSES.items():
        enabled = os.environ.get(f"CONN_{prefix}_ENABLED", "false").lower() == "true"
        instance = cls(enabled=enabled)
        _registry[instance.name] = instance


def get_connector(name: str) -> Connector | None:
    return _registry.get(name)


def list_connectors() -> list[Connector]:
    return list(_registry.values())


def connector_tools() -> list[dict[str, Any]]:
    """Aggregate tool definitions from all registered connectors."""
    tools: list[dict[str, Any]] = []
    for c in _registry.values():
        tools.extend(c.tools())
    return tools
