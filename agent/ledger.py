"""The verified step ledger. Owner: CORE. This file is the heart of the project.

Rules that must always hold:
  - A step becomes `verified` only from a read of the target system, never from the write response.
  - Every write to a mock carries the step's idempotency_key.
  - Status only moves forward: planned -> sent -> verified | failed. Re-plans mark steps `skipped`.
"""
from datetime import datetime, timedelta, timezone

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from core import config
from core.db import get_db
from core.models import Step


LEASE_MINUTES = 2


def _step_id(step: Step) -> dict:
    return {"run_id": step.run_id, "seq": step.seq, "idempotency_key": step.idempotency_key}


def _read_step(document: dict) -> Step:
    document.pop("_id", None)
    return Step.model_validate(document)


def write_plan(run_id: str, steps: list[Step]) -> None:
    """Insert planned steps. Must be safe to call twice (unique idempotency_key)."""
    collection = get_db()[config.STEPS]
    for step in steps:
        if step.run_id != run_id:
            raise ValueError("step run_id does not match plan run_id")
        try:
            collection.insert_one(step.model_dump())
        except DuplicateKeyError:
            # Reopen a dead step but keep attempts and token, so retries stay counted and fenced.
            collection.update_one(
                {
                    "idempotency_key": step.idempotency_key,
                    "status": {"$in": ["skipped", "failed"]},
                },
                {"$set": {
                    "status": "planned",
                    "seq": step.seq,
                    "request": step.request,
                    "reason": step.reason,
                    "lease_owner": None,
                    "lease_expires": None,
                    "updated_at": datetime.now(timezone.utc),
                }},
            )


def next_step(run_id: str, worker_id: str) -> Step | None:
    """Atomically claim the next planned step with find_one_and_update."""
    now = datetime.now(timezone.utc)
    collection = get_db()[config.STEPS]
    candidates = collection.find({"run_id": run_id, "status": "planned"}).sort("seq", 1)
    for candidate in candidates:
        if collection.find_one({
            "run_id": run_id,
            "seq": {"$lt": candidate["seq"]},
            # A failed step is settled. run.py re-plans after any failure, so it must not block its replacement.
            "status": {"$nin": ["verified", "skipped", "failed"]},
        }):
            continue
        document = collection.find_one_and_update(
            {
                "_id": candidate["_id"],
                "status": "planned",
                "$or": [
                    {"lease_expires": None},
                    {"lease_expires": {"$exists": False}},
                    {"lease_expires": {"$lte": now}},
                    {"lease_owner": worker_id},  # a restarted worker takes back its own lease
                ],
            },
            {
                "$set": {
                    "lease_owner": worker_id,
                    "lease_expires": now + timedelta(minutes=LEASE_MINUTES),
                    "updated_at": now,
                },
                "$inc": {"attempts": 1, "token": 1},
            },
            return_document=ReturnDocument.AFTER,
        )
        if document:
            return _read_step(document)
    return None


def mark_sent(step: Step) -> None:
    _advance(step, "planned", "sent")


def mark_verified(step: Step, evidence: dict, verified_by: str) -> None:
    _advance(step, "sent", "verified", evidence=evidence, verified_by=verified_by)


def mark_failed(step: Step, evidence: dict) -> None:
    _advance(step, "sent", "failed", evidence=evidence)


def skip_planned(run_id: str) -> int:
    """Mark every planned step skipped so the run can re-plan after a failure."""
    result = get_db()[config.STEPS].update_many(
        {"run_id": run_id, "status": "planned"},
        {"$set": {
            "status": "skipped",
            "lease_owner": None,
            "lease_expires": None,
            "updated_at": datetime.now(timezone.utc),
        }},
    )
    return result.modified_count


def unresolved_sent_steps(run_id: str) -> list[Step]:
    """Steps whose outcome is unknown. Resume starts here."""
    documents = get_db()[config.STEPS].find({"run_id": run_id, "status": "sent"}).sort("seq", 1)
    return [_read_step(document) for document in documents]


def _advance(step: Step, expected: str, target: str, **fields: object) -> None:
    now = datetime.now(timezone.utc)
    fields.update({"status": target, "updated_at": now, "lease_expires": None})
    result = get_db()[config.STEPS].update_one(
        {**_step_id(step), "status": expected},
        {"$set": fields},
    )
    if result.matched_count != 1:
        raise RuntimeError(f"cannot move step {step.idempotency_key} from {expected} to {target}")
