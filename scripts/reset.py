"""Put the demo back to its starting state. Run: bash scripts/dev.sh reset

Clears every run, step, event, proposal and worker, deletes approved rules and restores corrected
incident memories, so the carrier change asks for approval again. Also resets the mocks if they are up.
Seeded incident memories and the shipment stay. Nothing is embedded again.
"""
import httpx

from core import config
from core.db import get_db


def reset(db) -> dict:
    cleared = {name: db[name].delete_many({}).deleted_count
               for name in (config.RUNS, config.STEPS, config.EVENTS, config.PROPOSALS, config.WORKERS)}
    cleared["approved_rules"] = db[config.MEMORIES].delete_many({"kind": "approved_rule"}).deleted_count
    db[config.MEMORIES].update_many({"kind": "incident_fix"}, {"$set": {"active": True, "superseded_by": None}})
    return cleared


def reset_mocks() -> dict:
    out = {}
    for name, url in (("carrier", config.CARRIER_URL), ("warehouse", config.WAREHOUSE_URL), ("hospital", config.HOSPITAL_URL)):
        try:
            httpx.post(url + "/admin/reset", timeout=3).raise_for_status()
            out[name] = "reset"
        except httpx.HTTPError:
            out[name] = "not running"
    return out


if __name__ == "__main__":
    print("Atlas:", reset(get_db()))
    print("Mocks:", reset_mocks())
