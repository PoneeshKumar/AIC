"""Drift handling. Owner: MEMORY.

When a system answers in a shape we do not understand:
  1. Summarize the failure (system, endpoint, what we expected, what we got).
  2. recall() similar incidents.
    3. Turn the closest recalled fix into a proposal for human approval.
    4. Write a proposal document and STOP until a human approves it in the UI.
    5. On approval, store it as an `approved_rule` memory and apply it to the rest of the run.

An approved rule is applied without asking again. That is the proof memory changed behaviour:
the second shipment that hits the same drift does not fail first.
"""
import hashlib
import json
import uuid
from datetime import datetime, timezone

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from core import config
from core.db import get_db
from agent import memory
from agent.memory import MIN_PROPOSAL_SCORE, recall
from core.models import Memory


class ProposalNotFound(LookupError):
    pass


class ProposalResolved(RuntimeError):
    pass


def failure_signature(failure: dict) -> str:
    """Stable hash of a failure document, used to dedupe pending proposals."""
    return hashlib.sha256(json.dumps(failure, sort_keys=True).encode()).hexdigest()


def propose_fix(failure: dict) -> dict:
    """Create a reviewable proposal from the closest approved incident memory."""
    system = failure.get("system", "unknown")
    query = json.dumps(failure, sort_keys=True)
    matches = recall(query, system)
    best_match = (
        matches[0]
        if matches and float(matches[0].get("score", 0)) >= MIN_PROPOSAL_SCORE
        else None
    )
    proposal = {
        "summary": (
            "Reuse the closest approved incident fix after human review"
            if best_match
            else "No matching incident found; provide a fix manually"
        ),
        "fix": best_match.get("fix", {}) if best_match else {},
    }
    document = {
        "proposal_id": str(uuid.uuid4()),
        "failure": failure,
        "matches": matches,
        "proposal": proposal,
        "created_at": datetime.now(timezone.utc),
    }
    collection = get_db()[config.PROPOSALS]
    signature = failure_signature(failure)
    try:
        result = collection.find_one_and_update(
            {"signature": signature, "status": "pending"},
            {"$setOnInsert": {**document, "signature": signature, "status": "pending"}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
    except DuplicateKeyError:
        result = collection.find_one({"signature": signature, "status": "pending"})
        if result is None:
            raise
    result["_id"] = str(result["_id"])
    return result


def resolve_proposal(
    db, proposal_id: str, action: str, rule: dict | None = None, approved_by: str = "human"
) -> dict:
    """Approve or correct a pending proposal. Only one caller can win the pending -> resolved move."""
    if action not in {"approve", "correct"}:
        raise ValueError(f"unknown action: {action}")
    collection = db[config.PROPOSALS]
    proposal = collection.find_one({"proposal_id": proposal_id})
    if not proposal:
        raise ProposalNotFound(proposal_id)
    if action == "approve":
        rule = proposal.get("proposal", {}).get("fix") or {}
    if not isinstance(rule, dict) or not isinstance(rule.get("map"), dict) or not rule["map"]:
        raise ValueError("a rule with a non-empty map is required")

    status = "approved" if action == "approve" else "corrected"
    claimed = collection.find_one_and_update(
        {"proposal_id": proposal_id, "status": "pending"},
        {"$set": {"status": status, "resolved_by": approved_by,
                  "resolved_at": datetime.now(timezone.utc), "rule": rule}},
        return_document=ReturnDocument.AFTER,
    )
    if claimed is None:
        raise ProposalResolved(proposal_id)

    try:
        system = claimed["failure"].get("system", "unknown")
        original = next(
            (m for m in claimed.get("matches", []) if m.get("kind") == "incident_fix"), None
        )
        if action == "correct" and original:
            memory_id = memory.correct(original["_id"], rule, approved_by)
        else:
            memory_id = memory.remember(Memory(
                kind="approved_rule",
                system=system,
                summary=f"Approved rule for {json.dumps(claimed['failure'], sort_keys=True)}",
                fix=rule,
                approved_by=approved_by,
            ))
    except Exception:
        collection.update_one(
            {"proposal_id": proposal_id, "status": status},
            {"$set": {"status": "pending"}, "$unset": {"resolved_by": "", "resolved_at": "", "rule": ""}},
        )
        raise
    updated = collection.find_one_and_update(
        {"proposal_id": proposal_id}, {"$set": {"rule_memory_id": memory_id}},
        return_document=ReturnDocument.AFTER,
    )
    updated["_id"] = str(updated["_id"])
    return updated


def apply_rule(rule: dict, raw_response: dict) -> dict:
    """Translate a response using an approved rule. Must be deterministic, no LLM call here."""
    translated: dict = {}
    for source, target in rule.get("map", {}).items():
        value = raw_response
        for part in target.split("."):
            if not isinstance(value, dict) or part not in value:
                raise KeyError(f"{source} -> {target} missing")
            value = value[part]
        translated[source] = value

    transforms = {
        "epoch_seconds_to_iso": lambda value: datetime.fromtimestamp(
            value, tz=timezone.utc
        ).isoformat().replace("+00:00", "Z"),
    }
    for field, transform in rule.get("transform", {}).items():
        if field not in translated:
            raise KeyError(f"transform field missing: {field}")
        if transform not in transforms:
            raise ValueError(f"unknown transform: {transform}")
        translated[field] = transforms[transform](translated[field])
    return translated
