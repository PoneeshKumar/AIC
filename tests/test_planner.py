from __future__ import annotations

from agent.planner import RouteOption, solve


def route(route_id: str, minutes: int, arrival: str, warehouse_id: str | None = None):
    return RouteOption(
        route_id=route_id,
        legs=[{"from": "YYZ", "to": "YVR", "arrive": arrival}],
        warehouse_id=warehouse_id,
        uncooled_minutes=minutes,
    )


def test_selects_route_with_most_budget_left_and_emits_ordered_steps():
    plan = solve(
        180,
        [route("direct", 120, "18:00"), route("cooled", 30, "19:00", "wh-yyc")],
        {"run_id": "run-1", "shipment_id": "BIO-2048"},
    )

    assert plan.chosen.route_id == "cooled"
    assert plan.budget_after_minutes == 150
    assert [step["action"] for step in plan.steps] == [
        "set_quarantine", "reserve_storage", "rebook_carrier", "notify_hospital"
    ]
    assert plan.steps[1]["idempotency_key"] == "run-1:reserve_storage:wh-yyc"


def test_reuses_verified_actions():
    plan = solve(
        180,
        [route("cooled", 30, "19:00", "wh-yyc")],
        {
            "run_id": "run-1",
            "shipment_id": "BIO-2048",
            "reservation": {"warehouse_id": "wh-yyc"},
            "booking": {"route_id": "cooled"},
        },
    )

    assert [step["action"] for step in plan.steps] == ["set_quarantine", "notify_hospital"]


def test_does_not_reuse_actions_for_different_route_or_warehouse():
    plan = solve(
        180,
        [route("route-y", 30, "19:00", "wh-b")],
        {
            "run_id": "run-1",
            "shipment_id": "BIO-2048",
            "reservation": {"warehouse_id": "wh-a"},
            "booking": {"route_id": "route-x"},
        },
    )

    assert [step["action"] for step in plan.steps] == [
        "set_quarantine", "reserve_storage", "rebook_carrier", "notify_hospital"
    ]


def test_no_feasible_route_returns_explanation():
    plan = solve(
        20,
        [route("late", 21, "19:00")],
        {"run_id": "run-1", "shipment_id": "BIO-2048"},
    )

    assert plan.chosen.route_id == "no-feasible-route"
    assert [step["action"] for step in plan.steps] == ["set_quarantine"]
    assert plan.rejected == [{"route_id": "late", "why": "needs 21 uncooled min, 20 left"}]


def test_same_input_is_deterministic():
    routes = [route("b", 30, "19:00"), route("a", 30, "19:00")]
    first = solve(100, routes, {"run_id": "run-1", "shipment_id": "BIO-2048"})
    second = solve(100, routes, {"run_id": "run-1", "shipment_id": "BIO-2048"})

    assert first == second
    assert first.chosen.route_id == "a"