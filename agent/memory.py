"""Failure memory on Atlas Vector Search with Voyage embeddings. Owner: MEMORY.

remember(): store a fix or an approved rule.
recall(): $vectorSearch for similar past incidents, filtered by system, skipping superseded ones.
correct(): mark a memory superseded and store the human's correction (the Track 2 beat).
"""
from core.models import Memory


def embed(text: str) -> list[float]:
    raise NotImplementedError


def remember(memory: Memory) -> str:
    raise NotImplementedError


def recall(query: str, system: str, k: int = 3) -> list[dict]:
    """Return memories with their similarity score so the UI can show 'memory hit (0.91)'."""
    raise NotImplementedError


def correct(memory_id: str, corrected_fix: dict, approved_by: str) -> str:
    raise NotImplementedError
