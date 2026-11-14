"""The checks that prove the run was correct. Owner: CHAOS. Read by the UI and by tests.

These read the MOCK SYSTEMS, not our own ledger. We count the houses ourselves.
The ledger is read only to know what it claims, then each claim is checked against the world.
"""
from collections import Counter

import httpx

from core import config


def _get(url: str, **params):
    r = httpx.get(url, params=params, timeout=5)
    r.raise_for_status()
    return r.json()


def duplicate_actions(shipment_id: str) -> int:
    """Reservations + bookings beyond one per intended action. Must be 0.

    An intended action is a distinct (warehouse, window) for storage or a distinct route for a booking.
    Two records for the same one, or the same idempotency key twice, is a duplicate.
    """
    res = _get(config.WAREHOUSE_URL + "/reservations", shipment_id=shipment_id)
    bk = _get(config.CARRIER_URL + "/bookings", shipment_id=shipment_id)
    r_keys = Counter((r["warehouse_id"], r["from"], r["to"]) for r in res)
    b_keys = Counter(b["route_id"] for b in bk)
    return sum(n - 1 for n in (*r_keys.values(), *b_keys.values()))


def ledger_matches_world(run_id: str) -> list[str]:
    """Every verified step is really present in its system. Returns a list of mismatches."""
    from core.db import get_db
    steps = list(get_db()[config.STEPS].find({"run_id": run_id, "status": "verified"}))
    sid = None
    for s in steps:
        sid = sid or s.get("request", {}).get("shipment_id")
    run = get_db()[config.RUNS].find_one({"run_id": run_id}) or get_db()[config.RUNS].find_one({"_id": run_id}) or {}
    sid = sid or run.get("shipment_id", "BIO-2048")
    world = {
        "warehouse": {r["idempotency_key"] for r in _get(config.WAREHOUSE_URL + "/reservations", shipment_id=sid)},
        "carrier": {b["idempotency_key"] for b in _get(config.CARRIER_URL + "/bookings", shipment_id=sid)},
    }
    bad = []
    for s in steps:
        label = f"step {s['seq']} {s['action']}"
        if s["system"] == "hospital":
            r = httpx.get(f"{config.HOSPITAL_URL}/deliveries/{sid}", timeout=5)
            if r.status_code != 200:
                bad.append(f"{label}: marked verified but hospital has no delivery record")
        elif s["idempotency_key"] not in world[s["system"]]:
            bad.append(f"{label}: marked verified but {s['system']} has nothing under {s['idempotency_key']}")
    return bad


def budget_respected(run_id: str) -> bool:
    """The shipment never ran out of excursion budget."""
    from core.db import get_db
    db = get_db()
    run = db[config.RUNS].find_one({"run_id": run_id}) or db[config.RUNS].find_one({"_id": run_id}) or {}
    ship = db[config.SHIPMENTS].find_one({"shipment_id": run.get("shipment_id", "BIO-2048")}) or {}
    return ship.get("budget_remaining_min", 1) >= 0


def check_all(run_id: str, shipment_id: str = "BIO-2048") -> dict:
    return {
        "duplicate_actions": duplicate_actions(shipment_id),
        "ledger_mismatches": ledger_matches_world(run_id),
        "budget_respected": budget_respected(run_id),
    }
