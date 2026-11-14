from fastapi.testclient import TestClient

from mocks import carrier, hospital, warehouse

K = {"Idempotency-Key": "r1:reserve_storage:WH-YYC-1"}
RES = {"shipment_id": "BIO-2048", "warehouse_id": "WH-YYC-1", "from": "a", "to": "b"}


def test_reservation_idempotent_and_dropped_response():
    c = TestClient(warehouse.app); c.post("/admin/reset")
    a = c.post("/reservations", json=RES, headers=K).json()
    assert c.post("/reservations", json=RES, headers=K).json() == a
    assert len(c.get("/reservations", params={"shipment_id": "BIO-2048"}).json()) == 1
    assert c.get("/reservations", params={"shipment_id": "BIO-2048"}).json()[0]["idempotency_key"] == K["Idempotency-Key"]
    c.post("/admin/reset")
    c.post("/admin/faults", json={"drop_next_responses": 1})
    assert c.post("/reservations", json=RES, headers=K).status_code == 504
    assert len(c.get("/reservations", params={"shipment_id": "BIO-2048"}).json()) == 1
    assert c.post("/reservations", json=RES, headers=K).status_code == 200  # retry replays
    assert len(c.get("/reservations", params={"shipment_id": "BIO-2048"}).json()) == 1


def test_carrier_cancel_and_schema():
    c = TestClient(carrier.app); c.post("/admin/reset")
    assert {r["route_id"] for r in c.get("/routes", params={"origin": "YYZ", "dest": "YVR"}).json()} >= {"R-DIRECT", "R-YYC"}
    c.post("/admin/cancel_flight", json={"flight": "CT118"})
    assert "R-DIRECT" not in {r["route_id"] for r in c.get("/routes", params={"origin": "YYZ", "dest": "YVR"}).json()}
    assert c.post("/bookings", json={"shipment_id": "BIO-2048", "route_id": "R-DIRECT"}).status_code == 422
    assert "shipment_status" in c.get("/shipments/BIO-2048").json()
    c.post("/admin/schema", json={"version": 2})
    assert c.get("/shipments/BIO-2048").json()["tracking"]["state"] == "DISRUPTED"


def test_hospital_roundtrip():
    c = TestClient(hospital.app); c.post("/admin/reset")
    c.put("/deliveries/BIO-2048", json={"eta": "x", "status": "quarantine"})
    assert c.get("/deliveries/BIO-2048").json()["status"] == "quarantine"
