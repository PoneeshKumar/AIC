import httpx
import mongomock
import pytest
from fastapi.testclient import TestClient

from agent import adapt, memory, run as agent_run
from core import config
from server import app as server

RULE = {"map": {"shipment_status": "tracking.state", "eta": "tracking.estimated_arrival_epoch"},
        "transform": {"eta": "epoch_seconds_to_iso"}}
V2 = {"tracking": {"state": "DISRUPTED", "estimated_arrival_epoch": 1794688800}}


@pytest.fixture
def db(monkeypatch):
    db = mongomock.MongoClient().coldtrace_drift
    for module in (adapt, memory, server):
        monkeypatch.setattr(module, "get_db", lambda: db)
    monkeypatch.setattr(memory, "embed", lambda text, input_type="document": [0.1, 0.2])
    monkeypatch.setattr(adapt, "recall", lambda query, system: [
        {"_id": "m1", "kind": "incident_fix", "score": 0.9, "fix": RULE}])
    return db


def carrier_returns(monkeypatch, payload):
    monkeypatch.setattr(agent_run.httpx, "get", lambda url, **kw: httpx.Response(
        200, json=payload, request=httpx.Request("GET", url)))


def parse(db, run_id="run-1"):
    return agent_run.parse_carrier_status(db, run_id, "w1", "BIO-2048")


def test_v1_parses_normally(db, monkeypatch):
    carrier_returns(monkeypatch, {"shipment_status": "delayed", "eta": "2026-11-14T18:00:00Z"})
    assert parse(db)["shipment_status"] == "delayed"
    assert db[config.PROPOSALS].count_documents({}) == 0


def test_unknown_schema_one_proposal_and_blocks(db, monkeypatch):
    carrier_returns(monkeypatch, V2)
    db[config.RUNS].insert_one({"run_id": "run-1", "status": "recovering"})
    assert parse(db) is None
    assert parse(db) is None
    assert db[config.PROPOSALS].count_documents({"status": "pending"}) == 1
    assert db[config.EVENTS].count_documents({"kind": "proposal"}) == 1
    run = db[config.RUNS].find_one({"run_id": "run-1"})
    assert (run["status"], run["blocked_reason"]) == ("blocked", "waiting_approval")


def test_duplicate_failure_from_second_run_makes_no_second_proposal(db, monkeypatch):
    carrier_returns(monkeypatch, V2)
    parse(db, "run-1")
    parse(db, "run-2")
    assert db[config.PROPOSALS].count_documents({"status": "pending"}) == 1


def test_approval_stores_rule_and_second_run_reuses_it(db, monkeypatch):
    carrier_returns(monkeypatch, V2)
    assert parse(db) is None
    proposal = db[config.PROPOSALS].find_one()
    client = TestClient(server.app)
    response = client.post("/approve", json={"proposal_id": proposal["proposal_id"], "action": "approve"})
    assert response.status_code == 200 and response.json()["status"] == "approved"
    assert db[config.MEMORIES].count_documents({"kind": "approved_rule"}) == 1

    result = parse(db, "run-2")
    assert result["shipment_status"] == "DISRUPTED"
    assert result["eta"].endswith("Z")
    assert db[config.PROPOSALS].count_documents({}) == 1


def test_correct_supersedes_original(db, monkeypatch):
    original = db[config.MEMORIES].insert_one(
        {"kind": "incident_fix", "system": "carrier", "summary": "old", "active": True,
         "superseded_by": None, "fix": {}}).inserted_id
    carrier_returns(monkeypatch, V2)
    monkeypatch.setattr(adapt, "recall", lambda q, s: [
        {"_id": str(original), "kind": "incident_fix", "score": 0.9, "fix": {}}])
    parse(db)
    pid = db[config.PROPOSALS].find_one()["proposal_id"]
    fixed = {"map": {"shipment_status": "tracking.state"}}
    response = TestClient(server.app).post(
        "/approve", json={"proposal_id": pid, "action": "correct", "rule": fixed})
    assert response.json()["status"] == "corrected"
    assert db[config.MEMORIES].find_one({"_id": original})["active"] is False
    assert db[config.MEMORIES].find_one({"kind": "approved_rule"})["fix"] == fixed


def test_correcting_a_model_draft_keeps_the_recalled_memory(db, monkeypatch):
    original = db[config.MEMORIES].insert_one(
        {"kind": "incident_fix", "system": "carrier", "summary": "old", "active": True,
         "superseded_by": None, "fix": {}}).inserted_id
    carrier_returns(monkeypatch, V2)
    monkeypatch.setattr(adapt, "recall", lambda q, s: [
        {"_id": str(original), "kind": "incident_fix", "score": 0.9, "fix": {}}])
    monkeypatch.setattr(adapt, "_ask_llm", lambda prompt: '{"fix": {"map": {"eta": "tracking.eta"}}, "reason": "moved"}')
    parse(db)
    proposal = db[config.PROPOSALS].find_one()
    assert proposal["proposal"]["source"] == "llm" and "memory_id" not in proposal["proposal"]
    fixed = {"map": {"shipment_status": "tracking.state"}}
    response = TestClient(server.app).post(
        "/approve", json={"proposal_id": proposal["proposal_id"], "action": "correct", "rule": fixed})
    assert response.json()["status"] == "corrected"
    assert db[config.MEMORIES].find_one({"_id": original})["active"] is True  # the draft did not come from it
    assert db[config.MEMORIES].find_one({"kind": "approved_rule"})["fix"] == fixed


def test_approve_missing_resolved_and_bad_body(db, monkeypatch):
    carrier_returns(monkeypatch, V2)
    parse(db)
    pid = db[config.PROPOSALS].find_one()["proposal_id"]
    client = TestClient(server.app)
    assert client.post("/approve", json={"proposal_id": "nope", "action": "approve"}).status_code == 404
    assert client.post("/approve", json={"proposal_id": pid, "action": "maybe"}).status_code == 400
    assert client.post("/approve", json={"proposal_id": pid, "action": "correct"}).status_code == 400
    assert client.post("/approve", json={"proposal_id": pid, "action": "approve"}).status_code == 200
    assert client.post("/approve", json={"proposal_id": pid, "action": "approve"}).status_code == 409
    assert db[config.MEMORIES].count_documents({"kind": "approved_rule"}) == 1


def test_approve_race_only_one_wins(db, monkeypatch):
    carrier_returns(monkeypatch, V2)
    parse(db)
    pid = db[config.PROPOSALS].find_one()["proposal_id"]
    db[config.PROPOSALS].update_one({"proposal_id": pid}, {"$set": {"status": "approved"}})
    with pytest.raises(adapt.ProposalResolved):
        adapt.resolve_proposal(db, pid, "approve")
    assert db[config.MEMORIES].count_documents({}) == 0
