"""The verified step ledger. Owner: CORE. This file is the heart of the project.

Rules that must always hold:
  - A step becomes `verified` only from a read of the target system, never from the write response.
  - Every write to a mock carries the step's idempotency_key.
  - Status only moves forward: planned -> sent -> verified | failed. Re-plans mark steps `skipped`.
"""
from core.models import Step


def write_plan(run_id: str, steps: list[Step]) -> None:
    """Insert planned steps. Must be safe to call twice (unique idempotency_key)."""
    raise NotImplementedError


def next_step(run_id: str, worker_id: str) -> Step | None:
    """Atomically claim the next planned step with find_one_and_update."""
    raise NotImplementedError


def mark_sent(step: Step) -> None:
    raise NotImplementedError


def mark_verified(step: Step, evidence: dict, verified_by: str) -> None:
    raise NotImplementedError


def mark_failed(step: Step, evidence: dict) -> None:
    raise NotImplementedError


def unresolved_sent_steps(run_id: str) -> list[Step]:
    """Steps whose outcome is unknown. Resume starts here."""
    raise NotImplementedError
