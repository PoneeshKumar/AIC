"""UI backend. Runs without Atlas: the mocks are wired in-process and Atlas is switched off."""
import pytest
from fastapi.testclient import TestClient

from core import config
from mocks import carrier, hospital, warehouse
from server import app as server

MOCKS = {"carrier": TestClient(carrier.app), "warehouse": TestClient(warehouse.app), "hospital": TestClient(hospital.app)}
RES = {"shipment_id": "BIO-2048", "warehouse_id": "WH-YYC-1", "from": "a", "to": "b"}


@pytest.fixture
def ui(monkeypatch):
    monkeypatch.setattr(config, "MONGODB_URI", "")
    monkeypatch.setattr(server, "call", lambda system, method, path, **kw: MOCKS[system].request(method, path, **kw))
    for c in MOCKS.values():
        c.post("/admin/reset")
    return TestClient(server.app)


def test_state_matches_contract_without_atlas(ui):
    st = ui.get("/state").json()
    assert set(st) == {"shipment", "counters", "steps", "systems", "proposal", "log"}
    assert st["shipment"] == {"shipment_id": "BIO-2048", "status": "in_transit", "budget_remaining_min": 480}
    assert st["counters"] == {"duplicate_actions": 0, "steps_verified": 0, "steps_total": 0}
    assert set(st["systems"]) == {"carrier", "warehouse", "hospital", "agent"}
    assert all(st["systems"][s]["ok"] for s in ("carrier", "warehouse", "hospital"))
    assert st["systems"]["agent"]["alive"] is False
    assert "Atlas is not connected" in st["log"][-1]["message"]


def test_state_reports_a_down_mock(ui, monkeypatch):
    import httpx

    def down(system, method, path, **kw):
        if system == "hospital":
            raise httpx.ConnectError("refused")
        return MOCKS[system].request(method, path, **kw)

    monkeypatch.setattr(server, "call", down)
    assert ui.get("/state").json()["systems"]["hospital"]["ok"] is False


def test_carrier_schema_and_reservations_come_from_the_mocks(ui):
    assert ui.post("/chaos/change_carrier").status_code == 200
    MOCKS["warehouse"].post("/reservations", json=RES, headers={"Idempotency-Key": "k1"})
    st = ui.get("/state").json()
    assert st["systems"]["carrier"]["schema_version"] == 2
    assert st["systems"]["warehouse"]["reservations"] == 1
    assert st["counters"]["duplicate_actions"] == 0


def test_duplicate_counter_sees_a_double_booking(ui):
    for key in ("k1", "k2"):  # two different keys is exactly the bug the counter must catch
        MOCKS["warehouse"].post("/reservations", json=RES, headers={"Idempotency-Key": key})
    assert ui.get("/state").json()["counters"]["duplicate_actions"] == 1


def test_cancel_flight_removes_the_direct_route(ui):
    assert ui.post("/chaos/cancel_flight").json()["message"] == "Flight CT118 cancelled"
    routes = MOCKS["carrier"].get("/routes", params={"origin": "YYZ", "dest": "YVR"}).json()
    assert "R-DIRECT" not in {r["route_id"] for r in routes}
    assert "Chaos: Flight CT118 cancelled" in [line["message"] for line in ui.get("/state").json()["log"]]


def test_drop_response_arms_the_warehouse(ui):
    ui.post("/chaos/drop_response")
    assert MOCKS["warehouse"].get("/admin/faults").json()["drop_next_responses"] == 1


def test_unbuilt_and_unknown_chaos_fail_clearly(ui):
    assert ui.post("/chaos/kill_agent").status_code == 501
    assert ui.post("/chaos/meteor").status_code == 404


def test_approve_needs_atlas(ui):
    assert ui.post("/approve", json={"proposal_id": "0" * 24}).status_code == 503


def test_static_ui_is_served(ui):
    page = ui.get("/").text
    assert "ColdTrace" in page and "/ui/app.js" in page
    assert ui.get("/ui/app.js").status_code == 200
    assert "never decides whether a product is safe" in page
