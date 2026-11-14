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
    assert adapt._llm_fix({}, []) is None  # unknown transform is rejected

    monkeypatch.setattr(adapt, "_ask_llm", lambda p: "not json")
    assert adapt._llm_fix({}, []) is None
