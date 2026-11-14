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
import threading
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


WAIT_FOR_EXIT_S = 60  # a run takes about 8 s against Atlas
HEARTBEAT_FRESH_S = 15  # a worker can sit in a 10 s request timeout between heartbeats


def _is_fresh(beat) -> bool:
    if not isinstance(beat, datetime):
        return False
    if beat.tzinfo is None:
        beat = beat.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - beat < timedelta(seconds=HEARTBEAT_FRESH_S)


def _running(pid) -> bool:
    """True while the process exists. This is what the operating system says, so it holds when Atlas is wrong."""
    if not pid:
        return False
    try:
        if os.waitpid(int(pid), os.WNOHANG)[0]:  # our own child that has exited keeps its pid until collected
            return False
    except ChildProcessError:
        pass  # not our child, for example an agent started from a terminal
    try:
        os.kill(int(pid), 0)  # signal 0 sends nothing, it only checks
    except ProcessLookupError:
        return False
    except PermissionError:
        pass  # it exists and belongs to another user
    return True


def _is_live(worker: dict) -> bool:
    """Live means the agent says so, said so recently, and its process still exists.

    The agent clears `alive` when it exits. The process check covers an agent that was killed or
    could not reach Atlas to sign off.
    """
    return bool(worker.get("alive")) and _is_fresh(worker.get("heartbeat")) and _running(worker.get("pid"))


_last_started: int | None = None  # the agent this process started last. It takes about 2 s to register in Atlas.
_queued = threading.Lock()         # held while one agent start waits for the working agent to exit


def _live_pid(worker: dict) -> int | None:
    """Pid of the agent that is working now, or None.

    Also true for an agent this process has just started and that has not registered yet. Without
    that, a second button press in those 2 s would start a second agent beside the first.
    """
    if _is_live(worker):
        return int(worker["pid"])
    try:
        if _last_started and os.waitpid(_last_started, os.WNOHANG)[0] == 0:  # our own child, still running
            return _last_started
    except ChildProcessError:
        pass  # already collected, so that pid is no longer ours
    return None


def _kill_agent() -> dict:
    db = get_db()
    target = db[config.RUNS].find_one(sort=[("_id", -1)]) or db[config.SHIPMENTS].find_one() or {}
    if not target.get("shipment_id"):
        raise RuntimeError("no run or shipment to restart the agent for")
    w = db[config.WORKERS].find_one({"pid": {"$exists": True}}, sort=[("heartbeat", -1)]) or {}
    killed = None
    # Only a recent heartbeat proves the pid is still our agent. A stale pid may belong to another program.
    pid = _live_pid(w)
    if pid:
        try:
            os.kill(pid, signal.SIGKILL)
            killed = pid
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
    global _last_started
    _last_started = p.pid
    return p.pid


def wake_agent() -> int | None:
    """Start the agent unless one is already working. Called when something changed that it must react to."""
    db = get_db()
    w = db[config.WORKERS].find_one({"pid": {"$exists": True}}, sort=[("heartbeat", -1)]) or {}
    ship = db[config.SHIPMENTS].find_one() or {}
    if not ship.get("shipment_id"):
        return None
    worker_id = w.get("worker_id", "worker-1")
    pid = _live_pid(w)
    if pid:
        # The working agent plans once, before its steps, so it will not see this change. Start a fresh
        # one the moment it exits. The fresh one reads the world first, so nothing is done twice.
        # One queued start is enough however many buttons are pressed.
        if _queued.acquire(blocking=False):
            threading.Thread(target=_start_after, args=(pid, ship["shipment_id"], worker_id)).start()
        return None
    return _start_agent(ship["shipment_id"], worker_id)


def _start_after(pid, shipment_id: str, worker_id: str) -> None:
    try:
        deadline = time.monotonic() + WAIT_FOR_EXIT_S
        while _running(pid) and time.monotonic() < deadline:
            time.sleep(0.5)
        if not _running(pid):  # still alive after the wait: leave it, two agents on one run would fight
            _start_agent(shipment_id, worker_id)
    finally:
        _queued.release()


def _drop_target() -> str:
    """The system the agent will write to next, so the dropped response is really hit and shows on screen.

    Once storage is held, a new run only writes to the hospital. Before that, the warehouse is the
    interesting one, because a blind retry there would hold a second bay.
    """
    ship = get_db()[config.SHIPMENTS].find_one() or {}
    try:
        held = httpx.get(config.WAREHOUSE_URL + "/reservations", params={"shipment_id": ship.get("shipment_id", "")}, timeout=5).json()
    except (httpx.HTTPError, ValueError):
        held = []
    return "hospital" if held else "warehouse"


def fire(event: str, run_id: str | None = None, **kw) -> dict:
    run_id = run_id or _latest_run_id()
    if event == "cancel_flight":
        flight = kw.get("flight", "CT118")
        out = {**_post(config.CARRIER_URL + "/admin/cancel_flight", {"flight": flight}), "agent_pid": wake_agent()}
        msg = f"chaos: flight {flight} cancelled" + (f", agent started as pid {out['agent_pid']}" if out["agent_pid"] else "")
    elif event == "change_carrier":
        # The agent only sees the new format when it runs, so start it like a cancelled flight does.
        out = {**_post(config.CARRIER_URL + "/admin/schema", {"version": kw.get("version", 2)}), "agent_pid": wake_agent()}
        msg = f"chaos: carrier API switched to schema v{kw.get('version', 2)}"
    elif event == "drop_response":
        system = kw.get("system") or _drop_target()
        out = {**_post(URLS[system] + "/admin/faults", {"drop_next_responses": 1}), "agent_pid": wake_agent()}
        msg = f"chaos: next {system} response will be dropped" + (f", agent started as pid {out['agent_pid']}" if out["agent_pid"] else "")
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
        try:
            results.append(fire(ev))
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
