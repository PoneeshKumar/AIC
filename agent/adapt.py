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
import json
from datetime import datetime, timezone

from pymongo import ReturnDocument

from core import config
from core.db import get_db
from agent.memory import MIN_PROPOSAL_SCORE, recall


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
        "status": "pending",
        "failure": failure,
        "matches": matches,
        "proposal": proposal,
    }
    result = get_db()[config.PROPOSALS].find_one_and_update(
        {"failure": failure, "status": "pending"},
        {"$setOnInsert": document},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    result["_id"] = str(result["_id"])
    return result


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
