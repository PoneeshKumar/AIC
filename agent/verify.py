"""Read-back checks, one per action. Owner: CORE.

Each function asks the target system what is true and returns (took_effect, evidence).
Example: for reserve_storage, GET /reservations?shipment_id=... and look for our idempotency key.
"""
import httpx

from core import config
from core.models import Step


def _raise_unless_not_found(response: httpx.Response) -> bool:
    if response.status_code == 404:
        return False
    response.raise_for_status()
    return True


def verify(step: Step) -> tuple[bool, dict]:
    if step.action == "reserve_storage":
        response = httpx.get(
            f"{config.WAREHOUSE_URL}/reservations",
            params={"shipment_id": step.request["shipment_id"]},
            timeout=10,
        )
        if not _raise_unless_not_found(response):
            return False, {"status_code": 404}
        reservations = response.json()
        matched = next(
            (item for item in reservations if item.get("idempotency_key") == step.idempotency_key),
            None,
        )
        return matched is not None, {"reservations": reservations, "matched": matched}

    if step.action == "rebook_carrier":
        response = httpx.get(
            f"{config.CARRIER_URL}/bookings",
            params={"shipment_id": step.request["shipment_id"]},
            timeout=10,
        )
        if not _raise_unless_not_found(response):
            return False, {"status_code": 404}
        bookings = response.json()
        matched = next(
            (item for item in bookings if item.get("idempotency_key") == step.idempotency_key),
            None,
        )
        return matched is not None, {"bookings": bookings, "matched": matched}

    if step.action in {"set_quarantine", "notify_hospital"}:
        response = httpx.get(
            f"{config.HOSPITAL_URL}/deliveries/{step.request['shipment_id']}",
            timeout=10,
        )
        if not _raise_unless_not_found(response):
            return False, {"status_code": 404}
        delivery = response.json()
        expected_status = step.request.get("status")
        expected_eta = step.request.get("eta")
        took_effect = (
            (expected_status is None or delivery.get("status") == expected_status)
            and (expected_eta is None or delivery.get("eta") == expected_eta)
        )
        return took_effect, delivery

    raise ValueError(f"unsupported verification action: {step.action}")
