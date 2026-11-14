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
