"""Atlas connection and indexes. Owner: CORE."""
from pymongo import ASCENDING, MongoClient

from core import config

_client = None


def get_db():
    global _client
    if _client is None:
        if not config.MONGODB_URI:
            raise RuntimeError("MONGODB_URI is empty. Copy .env.example to .env and fill it in.")
        _client = MongoClient(config.MONGODB_URI)
    return _client[config.MONGODB_DB]


def ensure_indexes():
    """Safe to call on every start."""
    db = get_db()
    # One step per idempotency key. This is what makes "never do it twice" enforceable.
    db[config.STEPS].create_index([("idempotency_key", ASCENDING)], unique=True)
    db[config.STEPS].create_index([("run_id", ASCENDING), ("seq", ASCENDING)])
    db[config.EVENTS].create_index([("run_id", ASCENDING), ("ts", ASCENDING)])
    # TODO(MEMORY): create the Atlas Vector Search index on memories.embedding
    # (filter fields: system, kind). Do this through the MongoDB MCP server or the Atlas UI.
