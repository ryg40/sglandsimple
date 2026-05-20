"""Mongo-backed LangGraph checkpointer.

Used purely for observability/debugging in stage 1 — clients don't pass
`thread_id`s and we never resume. Persisted runs let us inspect graph
execution in mongosh after the fact.
"""

from __future__ import annotations

import os
from contextlib import contextmanager

from langgraph.checkpoint.mongodb import MongoDBSaver

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://mongo:27017")
MONGO_DB = os.environ.get("MONGO_DB", "enterprise")
CHECKPOINT_COLLECTION = os.environ.get("LANGGRAPH_CHECKPOINT_COLLECTION", "lg_checkpoints")


@contextmanager
def checkpointer_context():
    """Open a MongoDBSaver context for one graph invocation."""
    with MongoDBSaver.from_conn_string(
        MONGO_URL,
        db_name=MONGO_DB,
        checkpoint_collection_name=CHECKPOINT_COLLECTION,
    ) as saver:
        yield saver
