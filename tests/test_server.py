from datetime import datetime, timezone

import mongomock
from fastapi.testclient import TestClient

from core import config
from server import app as server


def test_state_assembles_contract(monkeypatch):
    db = mongomock.MongoClient().coldtrace
    now = datetime.now(timezone.utc)
    db[config.SHIPMENTS].insert_one({
        "shipment_id": "BIO-2048",
        "excursion_budget_minutes": 222,
        "updated_at": now,
    })
    db[config.RUNS].insert_one({
        "run_id": "run-1",
        "shipment_id": "BIO-2048",
        "status": "recovering",
        "budget_after_minutes": 180,
        "created_at": now,
    })
    db[config.STEPS].insert_one({
        "run_id": "run-1", "seq": 1, "action": "set_quarantine",
        "system": "hospital", "status": "verified", "reason": "protect shipment",
    })
    db[config.EVENTS].insert_one({
        "run_id": "run-1", "ts": now, "message": "verified quarantine",
    })
    monkeypatch.setattr(server, "get_db", lambda: db)
    monkeypatch.setattr(server, "_health", lambda _: {"ok": True})

    response = TestClient(server.app).get("/state")

    assert response.status_code == 200
    body = response.json()
    assert body["shipment"]["shipment_id"] == "BIO-2048"
    assert body["counters"] == {"duplicate_actions": 0, "steps_verified": 1, "steps_total": 1}
    assert body["steps"][0]["status"] == "verified"
    assert body["log"][0]["message"] == "verified quarantine"


def test_state_reports_atlas_auth_failure(monkeypatch):
    from pymongo.errors import OperationFailure

    monkeypatch.setattr(server, "get_db", lambda: (_ for _ in ()).throw(
        OperationFailure("Authentication failed.")
    ))

    response = TestClient(server.app).get("/state")

    assert response.status_code == 503
    assert response.json()["detail"] == "Atlas is unavailable. Check MONGODB_URI credentials in .env."