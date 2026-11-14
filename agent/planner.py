"""Route and storage re-solve. Owner: PLANNER (Poneesh).

Input: the shipment's remaining excursion budget, the routes the carrier offers right now,
and warehouse capacity along each route.
Output: the option that leaves the most budget, plus the ordered steps to execute it.

Keep it small and exact. With 3 to 6 candidate routes, enumerate and score. Use scipy only
if you add constraints that make enumeration awkward.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


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
    run_id = verified_state["run_id"]
    shipment_id = verified_state["shipment_id"]
    existing_reservation = verified_state.get("reservation")
    existing_booking = verified_state.get("booking")
    reserved_warehouse = (
        existing_reservation.get("warehouse_id")
        if existing_reservation else None
    )

    feasible: list[tuple[RouteOption, int]] = []
    rejected: list[dict] = []
    for route in routes:
        uncooled = route.uncooled_minutes
        if route.warehouse_id and reserved_warehouse == route.warehouse_id:
            uncooled = 0
        if uncooled > budget_minutes:
            rejected.append({
                "route_id": route.route_id,
                "why": f"needs {uncooled} uncooled min, {budget_minutes} left",
            })
            continue
        feasible.append((route, budget_minutes - uncooled))

    if not feasible:
        sentinel = RouteOption(route_id="no-feasible-route", legs=[])
        return Plan(
            chosen=sentinel,
            budget_after_minutes=budget_minutes,
            rejected=rejected,
            steps=[{
                "action": "set_quarantine",
                "target": shipment_id,
                "idempotency_key": f"{run_id}:set_quarantine:{shipment_id}",
                "reason": "No feasible recovery route, so keep the shipment quarantined",
                "request": {"shipment_id": shipment_id, "status": "quarantined"},
            }],
        )

    def total_minutes(route: RouteOption) -> int:
        return sum(leg.get("duration_min", 0) for leg in route.legs)

    def arrival(route: RouteOption) -> str:
        """Use the leg's own arrival if it has one, else now plus the route's duration."""
        if route.legs and route.legs[-1].get("arrive"):
            return str(route.legs[-1]["arrive"])
        eta = datetime.now(timezone.utc) + timedelta(minutes=total_minutes(route))
        return eta.isoformat(timespec="seconds")

    chosen, budget_after = min(
        feasible,
        key=lambda item: (-item[1], str(item[0].legs[-1].get("arrive", "")) if item[0].legs else "", total_minutes(item[0]), item[0].route_id),
    )
    target = chosen.route_id
    steps: list[dict] = []

    def add_step(action: str, step_target: str, reason: str, request: dict) -> None:
        steps.append({
            "action": action,
            "target": step_target,
            "idempotency_key": f"{run_id}:{action}:{step_target}",
            "reason": reason,
            "request": request,
        })

    add_step(
        "set_quarantine",
        shipment_id,
        "Quarantine the shipment while the recovery route is confirmed",
        {"shipment_id": shipment_id, "status": "quarantined"},
    )
    if chosen.warehouse_id and reserved_warehouse != chosen.warehouse_id:
        add_step(
            "reserve_storage",
            chosen.warehouse_id,
            f"Hold qualified cold storage for the {chosen.route_id} layover",
            {"shipment_id": shipment_id, "warehouse_id": chosen.warehouse_id},
        )
    if not existing_booking or existing_booking.get("route_id") != chosen.route_id:
        add_step(
            "rebook_carrier",
            target,
            f"Rebook the shipment onto the route with {budget_after} excursion minutes left",
            {"shipment_id": shipment_id, "route_id": chosen.route_id},
        )
    add_step(
        "notify_hospital",
        shipment_id,
        "Tell the hospital the expected arrival for the selected route",
        {
            "shipment_id": shipment_id,
            "route_id": chosen.route_id,
            "eta": arrival(chosen),
            "status": "quarantined",
        },
    )
    return Plan(chosen=chosen, budget_after_minutes=budget_after, rejected=rejected, steps=steps)
