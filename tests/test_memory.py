"""Offline check for the MEMORY seed file. No Atlas, Voyage or LLM needed."""
import json
from pathlib import Path

SEED = Path(__file__).resolve().parent.parent / "data" / "seed" / "past_incidents.json"


def test_incident_file_is_valid():
    inc = json.load(open(SEED))["incidents"]
    assert 15 <= len(inc) <= 20
    assert {i["system"] for i in inc} == {"carrier", "warehouse", "hospital"}
    assert len({i["summary"] for i in inc}) == len(inc)
    assert all(i["kind"] == "incident_fix" and i["fix"] for i in inc)


def test_llm_fix_parses_validates_and_falls_back(monkeypatch):
    from agent import adapt

    good = '```json\n{"fix": {"map": {"eta": "tracking.estimated_arrival_epoch"}, "transform": {"eta": "epoch_seconds_to_iso"}}, "reason": "moved"}\n```'
    monkeypatch.setattr(adapt, "_ask_llm", lambda p: good)
    out = adapt._llm_fix({"system": "carrier"}, [{"summary": "s", "fix": {}, "score": 0.9}])
    assert out["fix"]["map"] == {"eta": "tracking.estimated_arrival_epoch"} and out["reason"] == "moved"

    monkeypatch.setattr(adapt, "_ask_llm", lambda p: '{"fix": {"map": {"eta": "x"}, "transform": {"eta": "rm_rf"}}}')
    assert "transform" in adapt._llm_fix({}, [])["error"]  # unknown transform is rejected

    monkeypatch.setattr(adapt, "_ask_llm", lambda p: "not json")
    assert "error" in adapt._llm_fix({}, [])


def test_propose_fix_reports_model_failure(monkeypatch):
    import mongomock

    from agent import adapt

    monkeypatch.setattr(adapt, "recall", lambda q, s: [{"_id": "m1", "summary": "s", "fix": {"map": {"eta": "x.y"}}, "score": 0.9}])
    monkeypatch.setattr(adapt, "get_db", lambda: mongomock.MongoClient()["t"])
    out = adapt.propose_fix({"system": "carrier"})["proposal"]
    assert out["source"] == "recalled_fix" and "no live LLM" in out["llm_error"]
    assert out["fix"] == {"map": {"eta": "x.y"}} and "unavailable" in out["summary"]


def test_vector_index_setup_creates_missing_collection(monkeypatch):
    import mongomock

    from core import config
    from core.db import ensure_memory_vector_index

    monkeypatch.setattr(mongomock.Collection, "list_search_indexes", lambda self: [], raising=False)  # mock has no Atlas search
    monkeypatch.setattr(mongomock.Collection, "create_search_index", lambda self, model: None, raising=False)
    db = mongomock.MongoClient()["fresh"]
    assert config.MEMORIES not in db.list_collection_names()
    ensure_memory_vector_index(db)
    assert config.MEMORIES in db.list_collection_names()


def test_reset_clears_runs_and_approved_rules_but_keeps_incidents():
    import mongomock

    from core import config
    from scripts.reset import reset

    db = mongomock.MongoClient()["reset"]
    db[config.RUNS].insert_one({"run_id": "r"})
    db[config.MEMORIES].insert_many([
        {"kind": "approved_rule", "active": True},
        {"kind": "incident_fix", "active": False, "superseded_by": "x"}])
    assert reset(db)["approved_rules"] == 1 and db[config.RUNS].count_documents({}) == 0
    assert list(db[config.MEMORIES].find({}, {"_id": 0})) == [{"kind": "incident_fix", "active": True, "superseded_by": None}]
