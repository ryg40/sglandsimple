"""Mongo-backed LangGraph checkpointer.

Used purely for observability/debugging in stage 1 — clients don't pass
`thread_id`s and we never resume. Persisted runs let us inspect graph
execution in mongosh after the fact.

As of langgraph-checkpoint-mongodb 0.4.0 (Stage 21 LangChain 1.x upgrade) the
separate ``AsyncMongoDBSaver`` / ``langgraph.checkpoint.mongodb.aio`` module was
removed; the unified ``MongoDBSaver`` now implements the async checkpointer
interface (``aput``/``aget_tuple``/``alist``) directly, so the saver instance
works under ``graph.ainvoke``. Note its ``from_conn_string`` is a **sync**
context manager (``@contextmanager``), so we enter it with ``with`` and re-expose
it through our own ``@asynccontextmanager`` for callers that ``async with`` it.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from langgraph.checkpoint.mongodb import MongoDBSaver

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://mongo:27017")
MONGO_DB = os.environ.get("MONGO_DB", "enterprise")
CHECKPOINT_COLLECTION = os.environ.get("LANGGRAPH_CHECKPOINT_COLLECTION", "lg_checkpoints")


@asynccontextmanager
async def checkpointer_context():
    """Open a MongoDBSaver context for one graph invocation (async-capable).

    ``from_conn_string`` is a sync context manager in checkpoint-mongodb 0.4.0;
    the yielded saver still serves the async checkpointer methods used under
    ``graph.ainvoke``.
    """
    with MongoDBSaver.from_conn_string(
        MONGO_URL,
        db_name=MONGO_DB,
        checkpoint_collection_name=CHECKPOINT_COLLECTION,
    ) as saver:
        yield saver
