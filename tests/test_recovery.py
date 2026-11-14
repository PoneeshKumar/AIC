"""The recovery loop end to end, on mongomock and the in-process mocks.

Each test breaks one thing and checks the run still ends verified with one reservation and one booking.
"""
import httpx
import mongomock
import pytest
from fastapi.testclient import TestClient

from agent import adapt, ledger, memory, run as agent_run, verify
from core import config
from mocks import carrier, hospital, warehouse
from mocks.common import seed
from server import app as server

MOCKS = {"carrier": TestClient(carrier.app), "warehouse": TestClient(warehouse.app), "hospital": TestClient(hospital.app)}
BASES = {config.CARRIER_URL: "carrier", config.WAREHOUSE_URL: "warehouse", config.HOSPITAL_URL: "hospital"}
SHIPMENT = "BIO-2048"
RULE = {"map": {"shipment_status": "tracking.state", "eta": "tracking.estimated_arrival_epoch"},
        "transform": {"eta": "epoch_seconds_to_iso"}}


def _http(method):
    def send(url, **kw):
        kw.pop("timeout", None)
        base = next(b for b in BASES if url.startswith(b))
        return MOCKS[BASES[base]].request(method, url[len(base):], **kw)
    return send


@pytest.fixture
def db(monkeypatch):
    db = mongomock.MongoClient().coldtrace_recovery
    db[config.STEPS].create_index("idempotency_key", unique=True)
    db[config.SHIPMENTS].insert_one(dict(seed("shipment.json")))
    for module in (agent_run, ledger, adapt, memory, server):
        monkeypatch.setattr(module, "get_db", lambda: db)
    monkeypatch.setattr(agent_run, "ensure_indexes", lambda: None)
    monkeypatch.setattr(config, "LANGSMITH_TRACING", False)
    for method in ("get", "post", "put"):
        monkeypatch.setattr(httpx, method, _http(method.upper()))
    for client in MOCKS.values():
        client.post("/admin/reset")
    MOCKS["carrier"].post("/admin/cancel_flight", json={"flight": "CT118"})
    return db


def start(db) -> dict:
    run_id = agent_run.run(SHIPMENT)
    return db[config.RUNS].find_one({"run_id": run_id})


def world() -> tuple[int, int]:
    """(reservations, bookings) as the warehouse and the carrier report them."""
    query = {"shipment_id": SHIPMENT}
    return (len(MOCKS["warehouse"].get("/reservations", params=query).json()),
            len(MOCKS["carrier"].get("/bookings", params=query).json()))


def statuses(db) -> list[str]:
    return [s["status"] for s in db[config.STEPS].find().sort("seq", 1)]


def test_happy_path_all_steps_verified(db):
    assert start(db)["status"] == "complete"
    assert statuses(db) == ["verified"] * 4 and world() == (1, 1)


def test_second_start_after_completion_books_nothing_twice(db):
    first = start(db)
    second = start(db)  # a new run with new idempotency keys, which is exactly when a blind agent would repeat itself
    assert first["status"] == second["status"] == "complete" and first["run_id"] != second["run_id"]
    assert world() == (1, 1)
    actions = [s["action"] for s in db[config.STEPS].find({"run_id": second["run_id"]}).sort("seq", 1)]
    assert actions == ["set_quarantine", "notify_hospital"]


def test_rejected_step_is_replanned_on_the_next_start(db):
    MOCKS["warehouse"].post("/admin/faults", json={"fail_next_requests": 1})
    assert start(db)["status"] == "recovering"
    assert statuses(db) == ["verified", "failed", "planned", "planned"]
    assert start(db)["status"] == "complete"
    assert statuses(db) == ["verified"] * 4 and world() == (1, 1)
    assert db[config.RUNS].count_documents({}) == 1


def test_dropped_response_is_resolved_by_reading_in_the_same_run(db):
    MOCKS["warehouse"].post("/admin/faults", json={"drop_next_responses": 1})
    assert start(db)["status"] == "complete"
    assert world() == (1, 1)


def test_failed_last_step_does_not_complete_the_run(db, monkeypatch):
    real = verify.verify
    monkeypatch.setattr(verify, "verify", lambda step: (False, {}) if step.action == "notify_hospital" else real(step))
    assert start(db)["status"] == "recovering"
    monkeypatch.setattr(verify, "verify", real)
    assert start(db)["status"] == "complete"
    assert world() == (1, 1) and db[config.RUNS].count_documents({}) == 1


def test_unreadable_carrier_does_not_count_as_approval(db, monkeypatch):
    db[config.RUNS].insert_one({"run_id": "r1", "shipment_id": SHIPMENT, "status": "blocked",
                                "blocked_reason": "waiting_approval"})
    routed = _http("GET")

    def get(url, **kw):
        if "/shipments/" in url:
            raise httpx.ConnectError("carrier down")
        return routed(url, **kw)

    monkeypatch.setattr(httpx, "get", get)
    run = start(db)
    assert (run["status"], run["blocked_reason"]) == ("blocked", "waiting_approval")
    assert db[config.STEPS].count_documents({}) == 0 and world() == (0, 0)


def test_schema_change_is_approved_from_the_screen_then_completes(db, monkeypatch):
    monkeypatch.setattr(config, "MONGODB_URI", "mongodb://test")
    monkeypatch.setattr(server, "_atlas_retry_at", 0.0)
    monkeypatch.setattr(server, "call", lambda system, method, path, **kw: MOCKS[system].request(method, path, **kw))
    monkeypatch.setattr(memory, "embed", lambda text, input_type="document": [0.1, 0.2])
    monkeypatch.setattr(adapt, "recall", lambda query, system: [
        {"_id": "m1", "kind": "incident_fix", "summary": "carrier moved eta", "score": 0.9, "fix": RULE}])
    MOCKS["carrier"].post("/admin/schema", json={"version": 2})
    ui = TestClient(server.app)

    assert start(db)["status"] == "blocked"
    st = ui.get("/state").json()
    assert st["shipment"]["status"] == "waiting_approval"
    card = st["proposal"]
    assert card["proposal_id"] == db[config.PROPOSALS].find_one()["proposal_id"]
    assert (card["system"], card["fix"], card["memory_hit"], card["score"]) == ("carrier", RULE, "carrier moved eta", 0.9)

    approved = ui.post("/approve", json={"proposal_id": card["proposal_id"], "decision": "approved"})
    assert approved.status_code == 200
    assert start(db)["status"] == "complete" and world() == (1, 1)
    assert ui.get("/state").json()["shipment"] == {
        "shipment_id": SHIPMENT, "status": "recovered", "budget_remaining_min": 480}


def test_recall_outage_still_proposes_and_is_not_repeated(db, monkeypatch):
    calls = []

    def down(query, system):
        calls.append(query)
        raise RuntimeError("voyage down")

    monkeypatch.setattr(adapt, "recall", down)
    failure = {"system": "carrier", "got": {"tracking": "dict"}}
    first, second = adapt.propose_fix(failure), adapt.propose_fix(failure)
    assert first["proposal_id"] == second["proposal_id"] and len(calls) == 1
    assert first["matches"] == [] and "voyage down" in first["recall_error"]


@pytest.mark.parametrize("rule", [
    {"map": {"eta": 5}},
    {"map": {"eta": "a.b"}, "transform": "epoch_seconds_to_iso"},
    {"map": {"eta": "a.b"}, "transform": {"eta": "rot13"}},
    {"map": {"eta": "a.b"}, "transform": {"other": "epoch_seconds_to_iso"}},
])
def test_rules_apply_rule_cannot_run_are_rejected(rule):
    with pytest.raises(ValueError):
        adapt._check_rule(rule)
    adapt._check_rule(RULE)
