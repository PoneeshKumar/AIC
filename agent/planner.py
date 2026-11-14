"""Route and storage re-solve. Owner: PLANNER (Poneesh).

Input: the shipment's remaining excursion budget, the routes the carrier offers right now,
and warehouse capacity along each route.
Output: the option that leaves the most budget, plus the ordered steps to execute it.

Keep it small and exact. With 3 to 6 candidate routes, enumerate and score. Use scipy only
if you add constraints that make enumeration awkward.
"""
from dataclasses import dataclass, field


@dataclass
class RouteOption:
    route_id: str
    legs: list[dict]                 # each leg: {"from", "to", "depart", "arrive", "cooled": bool}
    warehouse_id: str | None = None  # qualified cold storage used during a layover
    uncooled_minutes: int = 0        # time that eats the excursion budget


@dataclass
class Plan:
    chosen: RouteOption
    budget_after_minutes: int
    rejected: list[dict] = field(default_factory=list)  # [{"route_id", "why"}] shown in the UI
    steps: list[dict] = field(default_factory=list)      # ordered actions for the ledger


def solve(budget_minutes: int, routes: list[RouteOption], verified_state: dict) -> Plan:
    """Must plan from VERIFIED state: a reservation that already exists is reused, not rebooked."""
    raise NotImplementedError
