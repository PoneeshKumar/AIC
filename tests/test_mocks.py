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


def test_write_requires_idempotency_key_and_fail_does_not_write():
    c = TestClient(warehouse.app); c.post("/admin/reset")
    assert c.post("/reservations", json=RES).status_code == 400
    c.post("/admin/faults", json={"fail_next_requests": 1})
    assert c.post("/reservations", json=RES, headers=K).status_code == 503
    assert c.get("/reservations", params={"shipment_id": "BIO-2048"}).json() == []


def test_carrier_cancel_and_schema():
    c = TestClient(carrier.app); c.post("/admin/reset")
    assert {r["route_id"] for r in c.get("/routes", params={"origin": "YYZ", "dest": "YVR"}).json()} >= {"R-DIRECT", "R-YYC"}
    c.post("/admin/cancel_flight", json={"flight": "CT118"})
    assert "R-DIRECT" not in {r["route_id"] for r in c.get("/routes", params={"origin": "YYZ", "dest": "YVR"}).json()}
    assert c.post(
        "/bookings",
        json={"shipment_id": "BIO-2048", "route_id": "R-DIRECT"},
        headers={"Idempotency-Key": "r1:rebook_carrier:R-DIRECT"},
    ).status_code == 422
    assert "shipment_status" in c.get("/shipments/BIO-2048").json()
    c.post("/admin/schema", json={"version": 2})
    assert c.get("/shipments/BIO-2048").json()["tracking"]["state"] == "DISRUPTED"


def test_carrier_booking_and_warehouse_capacity():
    carrier_client = TestClient(carrier.app); carrier_client.post("/admin/reset")
    booking = carrier_client.post(
        "/bookings",
        json={"shipment_id": "BIO-2048", "route_id": "R-DIRECT"},
        headers={"Idempotency-Key": "r1:rebook_carrier:R-DIRECT"},
    )
    assert booking.status_code == 200
    assert carrier_client.get("/bookings", params={"shipment_id": "BIO-2048"}).json() == [booking.json()]

    warehouse_client = TestClient(warehouse.app); warehouse_client.post("/admin/reset")
    capacity = warehouse_client.get("/capacity", params={"city": "YYC"}).json()
    assert capacity[0]["bays_free"] == 2
    warehouse_client.post("/reservations", json=RES, headers=K)
    assert warehouse_client.get("/capacity", params={"city": "YYC"}).json()[0]["bays_free"] == 1


def test_hospital_roundtrip():
    c = TestClient(hospital.app); c.post("/admin/reset")
    headers = {"Idempotency-Key": "r1:set_quarantine:hospital"}
    first = c.put("/deliveries/BIO-2048", json={"eta": "x", "status": "quarantine"}, headers=headers)
    assert c.put("/deliveries/BIO-2048", json={"eta": "changed", "status": "changed"}, headers=headers).json() == first.json()
    assert c.get("/deliveries/BIO-2048").json()["status"] == "quarantine"
