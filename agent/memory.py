"""Failure memory on Atlas Vector Search with Voyage embeddings. Owner: MEMORY.

remember(): store a fix or an approved rule.
recall(): $vectorSearch for similar past incidents, filtered by system, skipping superseded ones.
correct(): mark a memory superseded and store the human's correction (the Track 2 beat).
"""
from bson import ObjectId

from core import config
from core.db import get_db
from core.models import Memory

_voyage_client = None
MIN_PROPOSAL_SCORE = 0.75


def _client():
    global _voyage_client
    if _voyage_client is None:
        if not config.VOYAGE_API_KEY or not config.VOYAGE_MODEL:
            raise RuntimeError("VOYAGE_API_KEY and VOYAGE_MODEL are required for memory retrieval")
        import voyageai

        _voyage_client = voyageai.Client(api_key=config.VOYAGE_API_KEY)
    return _voyage_client


def embed_many(texts: list[str], input_type: str = "document") -> list[list[float]]:
    """Embed multiple incident summaries in one Voyage request."""
    if not texts:
        return []
    result = _client().embed(texts, model=config.VOYAGE_MODEL, input_type=input_type)
    return [list(embedding) for embedding in result.embeddings]


def embed(text: str, input_type: str = "document") -> list[float]:
    """Embed one memory summary for storage or vector recall."""
    return embed_many([text], input_type=input_type)[0]


def remember(memory: Memory) -> str:
    if not memory.embedding:
        memory.embedding = embed(memory.summary, input_type="document")
    result = get_db()[config.MEMORIES].insert_one(memory.model_dump())
    return str(result.inserted_id)


def recall(query: str, system: str, k: int = 3) -> list[dict]:
    """Return memories with their similarity score so the UI can show 'memory hit (0.91)'."""
    pipeline = [
        {
            "$vectorSearch": {
                "index": "memory_embedding",
                "path": "embedding",
                "queryVector": embed(query, input_type="query"),
                "numCandidates": max(k * 10, 20),
                "limit": k,
                "filter": {
                    "system": system,
                    "active": True,
                    "kind": {"$in": ["incident_fix", "approved_rule"]},
                },
            }
        },
        {"$set": {"score": {"$meta": "vectorSearchScore"}}},
        {"$project": {"embedding": 0}},
    ]
    matches = list(get_db()[config.MEMORIES].aggregate(pipeline))
    for match in matches:
        match["_id"] = str(match["_id"])
    return matches


def correct(memory_id: str, corrected_fix: dict, approved_by: str) -> str:
    collection = get_db()[config.MEMORIES]
    original = collection.find_one({"_id": ObjectId(memory_id), "superseded_by": None})
    if not original:
        raise ValueError(f"memory not found or already superseded: {memory_id}")
    replacement = Memory(
        kind="approved_rule",
        system=original["system"],
        summary=f"Human correction of {original['summary']}",
        fix=corrected_fix,
        approved_by=approved_by,
    )
    replacement_id = remember(replacement)
    result = collection.update_one(
        {"_id": ObjectId(memory_id), "superseded_by": None, "active": True},
        {"$set": {"superseded_by": replacement_id, "active": False}},
    )
    if result.matched_count != 1:
        raise RuntimeError(f"memory was corrected concurrently: {memory_id}")
    return replacement_id
