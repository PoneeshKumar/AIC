"""Fault injector. Owner: CHAOS. Build this FIRST, it is the test harness all day.

Named events (each one is also a button in the UI):
  cancel_flight    -> POST carrier /admin/cancel_flight
  kill_agent       -> SIGKILL the pid in `workers`, then restart it after a pause
  change_carrier   -> POST carrier /admin/schema {"version": 2}
  drop_response    -> POST <system> /admin/faults {"drop_next_responses": 1}
  random           -> pick one of the above at a random moment, seeded so a run can be replayed

Every event writes an Event(kind="chaos") so the UI log shows what was done to the system.

CLI: python -m chaos.injector <event> [--flight CT118] [--system warehouse] [--run RUN_ID]
     python -m chaos.injector random --seed 7 [--count 5]
"""
import argparse
import json
import os
import random
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import httpx

from core import config
from core.db import get_db
from core.models import Event

EVENTS = ["cancel_flight", "kill_agent", "change_carrier", "drop_response"]
URLS = {"carrier": config.CARRIER_URL, "warehouse": config.WAREHOUSE_URL, "hospital": config.HOSPITAL_URL}


def _post(url: str, body: dict) -> dict:
    r = httpx.post(url, json=body, timeout=5)
    r.raise_for_status()
    return r.json()


def _latest_run_id() -> str:
    run = get_db()[config.RUNS].find_one(sort=[("_id", -1)])
    return str(run.get("run_id", run["_id"])) if run else "none"


def _log(run_id: str, message: str, data: dict):
    get_db()[config.EVENTS].insert_one(Event(run_id=run_id, worker="chaos", kind="chaos", message=message, data=data).model_dump())


HEARTBEAT_FRESH_S = 15  # a worker can sit in a 10 s request timeout between heartbeats


def _is_fresh(beat) -> bool:
    if not isinstance(beat, datetime):
        return False
    if beat.tzinfo is None:
        beat = beat.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - beat < timedelta(seconds=HEARTBEAT_FRESH_S)


def _kill_agent() -> dict:
    db = get_db()
    target = db[config.RUNS].find_one(sort=[("_id", -1)]) or db[config.SHIPMENTS].find_one() or {}
    if not target.get("shipment_id"):
        raise RuntimeError("no run or shipment to restart the agent for")
    w = db[config.WORKERS].find_one({"pid": {"$exists": True}}, sort=[("heartbeat", -1)]) or {}
    killed = None
    # Only a recent heartbeat proves the pid is still our agent. A stale pid may belong to another program.
    if _is_fresh(w.get("heartbeat")):
        try:
            os.kill(int(w["pid"]), signal.SIGKILL)
            killed = w["pid"]
        except ProcessLookupError:
            pass  # it finished on its own just now
        time.sleep(2)
    return {"killed_pid": killed, "restarted_pid": _start_agent(target["shipment_id"], w.get("worker_id", "worker-1"))}


def _start_agent(shipment_id: str, worker_id: str = "worker-1") -> int:
    # ponytail: restarts as a plain child, a supervisor would be sturdier but this is a demo
    p = subprocess.Popen(
        [sys.executable, "-m", "agent.run", "--shipment", shipment_id, "--worker-id", worker_id],
        start_new_session=True,
    )
    return p.pid


def _wake_agent() -> int | None:
    """A cancelled flight is the trigger for recovery, so start the agent unless one is already working."""
    db = get_db()
    w = db[config.WORKERS].find_one({"pid": {"$exists": True}}, sort=[("heartbeat", -1)]) or {}
    if _is_fresh(w.get("heartbeat")):
        return None  # the live worker re-reads routes on its next plan
    ship = db[config.SHIPMENTS].find_one() or {}
    return _start_agent(ship["shipment_id"], w.get("worker_id", "worker-1")) if ship.get("shipment_id") else None


def fire(event: str, run_id: str | None = None, **kw) -> dict:
    run_id = run_id or _latest_run_id()
    if event == "cancel_flight":
        flight = kw.get("flight", "CT118")
        out = {**_post(config.CARRIER_URL + "/admin/cancel_flight", {"flight": flight}), "agent_pid": _wake_agent()}
        msg = f"chaos: flight {flight} cancelled" + (f", agent started as pid {out['agent_pid']}" if out["agent_pid"] else "")
    elif event == "change_carrier":
        out = _post(config.CARRIER_URL + "/admin/schema", {"version": kw.get("version", 2)})
        msg = f"chaos: carrier API switched to schema v{kw.get('version', 2)}"
    elif event == "drop_response":
        system = kw.get("system", "warehouse")
        out = _post(URLS[system] + "/admin/faults", {"drop_next_responses": 1})
        msg = f"chaos: next {system} response will be dropped"
    elif event == "kill_agent":
        out = _kill_agent()
        msg = (f"chaos: agent pid {out['killed_pid']} killed, restarted as {out['restarted_pid']}" if out["killed_pid"]
               else f"chaos: no agent was running, started one as pid {out['restarted_pid']}")
    else:
        raise ValueError(f"unknown event {event!r}, choose from {EVENTS}")
    _log(run_id, msg, {"event": event, **out})
    return {"event": event, "message": msg, **out}


def random_run(seed: int, count: int = 5) -> list[dict]:
    """Fire `count` events at random moments. Same seed, same events and gaps."""
    rng = random.Random(seed)
    results = []
    for _ in range(count):
        time.sleep(rng.uniform(1, 4))
        ev = rng.choice(EVENTS)
        kw = {"system": rng.choice(list(URLS))} if ev == "drop_response" else {}
        try:
            results.append(fire(ev, **kw))
        except Exception as e:  # keep attacking, a failed injection is itself a result
            results.append({"event": ev, "error": str(e)})
    return results


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("event", choices=EVENTS + ["random"])
    ap.add_argument("--flight"), ap.add_argument("--system"), ap.add_argument("--run")
    ap.add_argument("--seed", type=int, default=0), ap.add_argument("--count", type=int, default=5)
    a = ap.parse_args()
    if a.event == "random":
        from chaos.invariants import check_all
        print(json.dumps(random_run(a.seed, a.count), indent=2, default=str))
        time.sleep(5)  # let the agent settle before judging it
        print(json.dumps(check_all(a.run or _latest_run_id()), indent=2))
    else:
        kw = {k: v for k, v in (("flight", a.flight), ("system", a.system)) if v}
        print(json.dumps(fire(a.event, run_id=a.run, **kw), indent=2, default=str))
