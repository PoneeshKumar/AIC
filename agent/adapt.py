"""Drift handling. Owner: MEMORY.

When a system answers in a shape we do not understand:
  1. Summarize the failure (system, endpoint, what we expected, what we got).
  2. recall() similar incidents.
    3. Ask the LLM to propose a mapping from the failure and the recalled fixes. If it fails, reuse the closest recalled fix.
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


ALLOWED_TRANSFORMS = {"epoch_seconds_to_iso"}  # keep in step with apply_rule

PROMPT = """A system we integrate with changed its response shape. Propose a field mapping from our expected field names to dotted paths in the new response.
Failure: {failure}
Similar past incidents and their fixes: {recalled}
Reply with JSON only: {{"fix": {{"map": {{"expected_field": "new.dotted.path"}}, "transform": {{"expected_field": "epoch_seconds_to_iso"}}}}, "reason": "one sentence"}}
Allowed transforms: {transforms}. Only describe the field mapping."""


def _ask_llm(prompt: str) -> str:
    import os

    import anthropic  # the SDK reads ANTHROPIC_API_KEY from the environment (.env is loaded by core.config)

    # ponytail: core/config.py has no LLM settings, so read the model here. Move it there if Poneesh adds them.
    model = os.getenv("LLM_MODEL") or "claude-opus-5-5"
    reply = anthropic.Anthropic().messages.create(
        model=model, max_tokens=2000, messages=[{"role": "user", "content": prompt}]
    )
    return next(b.text for b in reply.content if b.type == "text")  # skip any thinking block


def _llm_fix(failure: dict, matches: list[dict]) -> dict:
    """Ask the model for a mapping. Returns {"fix", "reason"}, or {"error": why} on any failure or bad shape."""
    recalled = [{"summary": m.get("summary"), "fix": m.get("fix"), "score": round(float(m.get("score", 0)), 3)}
                for m in matches]
    try:
        text = _ask_llm(PROMPT.format(failure=json.dumps(failure, sort_keys=True), recalled=json.dumps(recalled),
                                      transforms=sorted(ALLOWED_TRANSFORMS)))
        out = json.loads(text[text.index("{"): text.rindex("}") + 1])
        fix = out["fix"]
        mapping = fix["map"]
        transform = fix.get("transform", {})
        if not mapping or not all(isinstance(k, str) and isinstance(v, str) for k, v in mapping.items()):
            return {"error": "model returned a bad field map"}
        if not all(k in mapping and v in ALLOWED_TRANSFORMS for k, v in transform.items()):
            return {"error": "model returned a transform we do not allow"}
        return {"fix": {"map": mapping, **({"transform": transform} if transform else {})},
                "reason": str(out.get("reason", ""))}
    except Exception as exc:  # no key, bad model name, rate limit, bad JSON: caller falls back and reports why
        return {"error": f"{type(exc).__name__}: {str(exc)[:150]}"}


def propose_fix(failure: dict) -> dict:
    """Create a reviewable proposal. The model drafts it, a human approves it, code applies it."""
    system = failure.get("system", "unknown")
    collection = get_db()[config.PROPOSALS]
    signature = failure_signature(failure)
    pending = collection.find_one({"signature": signature, "status": "pending"})
    if pending:  # already waiting on a human, so do not call Voyage or the model again
        pending["_id"] = str(pending["_id"])
        return pending
    query = json.dumps(failure, sort_keys=True)
    recall_error = None
    try:
        matches = recall(query, system)
    except Exception as exc:  # Voyage or the vector index is down: still propose, with no memory to lean on
        matches, recall_error = [], f"{type(exc).__name__}: {str(exc)[:150]}"
    best_match = (
        matches[0]
        if matches and float(matches[0].get("score", 0)) >= MIN_PROPOSAL_SCORE
        else None
    )
    drafted = _llm_fix(failure, matches)
    if "fix" in drafted:
        proposal = {"summary": f"Model proposed this mapping. {drafted['reason']}".strip(), "fix": drafted["fix"],
                    "source": "llm"}
    else:
        proposal = {
            "summary": (
                "Reuse the closest approved incident fix after human review"
                if best_match
                else "No matching incident found, so provide a fix manually"
            ),
            "fix": best_match.get("fix", {}) if best_match else {},
            "source": "recalled_fix",
            "llm_error": drafted["error"],  # why the model draft was not used, so run.py and the UI can show it
        }
        if best_match:
            proposal["summary"] = "Model unavailable, reused the closest approved incident fix after human review"
            proposal["memory_id"] = best_match.get("_id")  # the memory this draft was copied from
    document = {
        "proposal_id": str(uuid.uuid4()),
        "failure": failure,
        "matches": matches,
        "proposal": proposal,
        "created_at": datetime.now(timezone.utc),
    }
    if recall_error:
        document["recall_error"] = recall_error
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


def _check_rule(rule) -> None:
    """Raise ValueError unless apply_rule can run this rule. A stored bad rule would break every later run."""
    if not isinstance(rule, dict) or not isinstance(rule.get("map"), dict) or not rule["map"]:
        raise ValueError("a rule with a non-empty map is required")
    if not all(isinstance(k, str) and isinstance(v, str) and v for k, v in rule["map"].items()):
        raise ValueError("every map entry must be a field name and a dotted path")
    transform = rule.get("transform", {})
    if not isinstance(transform, dict) or not all(
        k in rule["map"] and isinstance(v, str) and v in ALLOWED_TRANSFORMS for k, v in transform.items()
    ):
        raise ValueError(f"transform must name a mapped field and one of {sorted(ALLOWED_TRANSFORMS)}")


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
    _check_rule(rule)

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
        # A correction replaces a memory only when the draft was copied from it. A model draft or a
        # weak match copied nothing, so the old memories stay and the human's rule is stored as new.
        copied_from = claimed.get("proposal", {}).get("memory_id")
        if action == "correct" and copied_from:
            memory_id = memory.correct(copied_from, rule, approved_by)
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
