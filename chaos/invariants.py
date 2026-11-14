"""The checks that prove the run was correct. Owner: CHAOS. Read by the UI and by tests.

These read the MOCK SYSTEMS, not our own ledger. We count the houses ourselves.
"""


def duplicate_actions(shipment_id: str) -> int:
    """Reservations + bookings beyond one per intended action. Must be 0."""
    raise NotImplementedError


def ledger_matches_world(run_id: str) -> list[str]:
    """Every verified step is really present in its system. Returns a list of mismatches."""
    raise NotImplementedError


def budget_respected(run_id: str) -> bool:
    raise NotImplementedError
