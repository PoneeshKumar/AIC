"""Atlas connection and indexes. Owner: CORE."""
from pymongo import ASCENDING, MongoClient

from core import config

_client = None

MEMORY_VECTOR_INDEX = {
    "name": "memory_embedding",
    "type": "vectorSearch",
    "definition": {
        "fields": [
            {"type": "vector", "path": "embedding", "numDimensions": 1024, "similarity": "cosine"},
            {"type": "filter", "path": "system"},
            {"type": "filter", "path": "kind"},
            {"type": "filter", "path": "active"},
        ],
    },
}


def get_db():
    global _client
    if _client is None:
        if not config.MONGODB_URI:
            raise RuntimeError("MONGODB_URI is empty. Copy .env.example to .env and fill it in.")
        # The driver default waits 30 s for an unreachable cluster, which freezes the screen.
        _client = MongoClient(config.MONGODB_URI, serverSelectionTimeoutMS=config.MONGODB_TIMEOUT_MS)
    return _client[config.MONGODB_DB]


def ensure_indexes():
    """Safe to call on every start."""
    db = get_db()
    # One step per idempotency key. This is what makes "never do it twice" enforceable.
    db[config.STEPS].create_index([("idempotency_key", ASCENDING)], unique=True)
    db[config.STEPS].create_index([("run_id", ASCENDING), ("seq", ASCENDING)])
    db[config.EVENTS].create_index([("run_id", ASCENDING), ("ts", ASCENDING)])
    db[config.WORKERS].create_index([("worker_id", ASCENDING)], unique=True)
    db[config.PROPOSALS].create_index(
        [("signature", ASCENDING)],
        unique=True,
        partialFilterExpression={"status": "pending"},
    )
    ensure_memory_vector_index(db)


def ensure_memory_vector_index(db=None):
    """Create the Atlas Vector Search index used by memory recall when supported."""
    if db is None:
        db = get_db()
    if config.MEMORIES not in db.list_collection_names():
        db.create_collection(config.MEMORIES)  # Atlas cannot index a collection that does not exist yet
    collection = db[config.MEMORIES]
    if not hasattr(collection, "list_search_indexes"):
        return
    existing = list(collection.list_search_indexes())
    if not any(index.get("name") == MEMORY_VECTOR_INDEX["name"] for index in existing):
        collection.create_search_index(MEMORY_VECTOR_INDEX)
