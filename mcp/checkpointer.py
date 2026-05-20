"""Mongo-backed LangGraph checkpointer.

Used purely for observability/debugging in stage 1 — clients don't pass
`thread_id`s and we never resume. Persisted runs let us inspect graph
execution in mongosh after the fact.

We use the async saver because all of our nodes are async; the sync
`MongoDBSaver` raises NotImplementedError under `graph.ainvoke`.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from langgraph.checkpoint.mongodb.aio import AsyncMongoDBSaver

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://mongo:27017")
MONGO_DB = os.environ.get("MONGO_DB", "enterprise")
CHECKPOINT_COLLECTION = os.environ.get("LANGGRAPH_CHECKPOINT_COLLECTION", "lg_checkpoints")


@asynccontextmanager
async def checkpointer_context():
    """Open an AsyncMongoDBSaver context for one graph invocation."""
    async with AsyncMongoDBSaver.from_conn_string(
        MONGO_URL,
        db_name=MONGO_DB,
        checkpoint_collection_name=CHECKPOINT_COLLECTION,
    ) as saver:
        yield saver
