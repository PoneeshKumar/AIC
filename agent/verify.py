"""Read-back checks, one per action. Owner: CORE.

Each function asks the target system what is true and returns (took_effect, evidence).
Example: for reserve_storage, GET /reservations?shipment_id=... and look for our idempotency key.
"""
from core.models import Step


def verify(step: Step) -> tuple[bool, dict]:
    raise NotImplementedError
