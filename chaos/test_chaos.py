"""Smoke check: duplicates counter against the real mocks. Run: pytest chaos -q"""
import threading, time
import sys, types
import httpx, uvicorn
try:
    import pymongo  # noqa
except ImportError:  # core.db imports it, the fakes below replace the real client anyway
    sys.modules["pymongo"] = types.SimpleNamespace(ASCENDING=1, MongoClient=None)
import pytest
from core import config


def _serve(app, port):
    s = uvicorn.Server(uvicorn.Config(app, port=port, log_level="error"))
    threading.Thread(target=s.run, daemon=True).start()
    time.sleep(0.8)


def test_duplicates(monkeypatch):
    from mocks.carrier import app as c
    from mocks.warehouse import app as w
    _serve(c, 18101), _serve(w, 18102)
    monkeypatch.setattr(config, "CARRIER_URL", "http://localhost:18101")
    monkeypatch.setattr(config, "WAREHOUSE_URL", "http://localhost:18102")
    from chaos.invariants import duplicate_actions
    body = {"shipment_id": "BIO-2048", "warehouse_id": "x", "from": "a", "to": "b"}
    wh = httpx.get("http://localhost:18102/capacity", params={"city": "YYC"}).json()[0]["warehouse_id"]
    body["warehouse_id"] = wh
    httpx.post("http://localhost:18102/reservations", json=body, headers={"Idempotency-Key": "k1"})
    assert duplicate_actions("BIO-2048") == 0
    httpx.post("http://localhost:18102/reservations", json=body, headers={"Idempotency-Key": "k2"})  # blind resend
    assert duplicate_actions("BIO-2048") == 1


class FakeColl:
    def __init__(self, docs): self.docs = docs
    def find(self, q):
        ok = lambda d, k, v: (k in d) == v["$exists"] if isinstance(v, dict) else d.get(k) == v  # only $exists supported
        return [d for d in self.docs if all(ok(d, k, v) for k, v in q.items())]
    def find_one(self, q=None, sort=None):
        r = self.find(q or {})
        return r[-1] if r else None


class FakeDB(dict):
    def __getitem__(self, k): return dict.get(self, k) or FakeColl([])


def test_budget_fails_closed(monkeypatch):
    import core.db
    from chaos.invariants import budget_respected
    monkeypatch.setattr(core.db, "get_db", lambda: FakeDB(runs=FakeColl([
        {"run_id": "a", "budget_after_minutes": 40}, {"run_id": "b", "budget_after_minutes": -5}])))
    assert budget_respected("a") and not budget_respected("b") and not budget_respected("missing")


def test_ledger_flags_phantom_step(monkeypatch):
    import core.db
    from chaos import invariants
    step = lambda seq, key: {"run_id": "r", "seq": seq, "action": "reserve_storage", "system": "warehouse",
                             "idempotency_key": key, "status": "verified", "request": {"shipment_id": "S"}}
    monkeypatch.setattr(core.db, "get_db", lambda: FakeDB(steps=FakeColl([step(1, "r:res:A"), step(2, "r:res:B")])))
    monkeypatch.setattr(invariants, "_get", lambda url, **kw: [{"idempotency_key": "r:res:A"}])
    bad = invariants.ledger_matches_world("r")
    assert len(bad) == 1 and "r:res:B" in bad[0]


def test_kill_agent(monkeypatch):
    import subprocess, core.db
    from chaos import injector
    from datetime import datetime, timedelta, timezone
    victim, bystander = subprocess.Popen(["sleep", "60"]), subprocess.Popen(["sleep", "60"])  # before Popen is faked
    now = datetime.now(timezone.utc)
    worker = {"pid": victim.pid, "worker_id": "w7", "heartbeat": now, "alive": True}
    monkeypatch.setattr(injector, "get_db", lambda: FakeDB(
        workers=FakeColl([worker]), runs=FakeColl([{"run_id": "r", "shipment_id": "BIO-2048"}])))
    monkeypatch.setattr(injector.time, "sleep", lambda s: None)
    spawned = []
    def fake_popen(argv, **k):
        spawned.append(argv)
        return types.SimpleNamespace(pid=99)
    monkeypatch.setattr(injector.subprocess, "Popen", fake_popen)
    out = injector._kill_agent()
    victim.wait(timeout=3)
    assert victim.returncode == -9 and out["killed_pid"] == victim.pid
    assert spawned[0][-4:] == ["--shipment", "BIO-2048", "--worker-id", "w7"]

    # A stale heartbeat means the pid may no longer be ours: kill nothing, still restart.
    worker.update(pid=bystander.pid, heartbeat=now - timedelta(minutes=5))
    out = injector._kill_agent()
    assert out["killed_pid"] is None and bystander.poll() is None and len(spawned) == 2
    bystander.kill()


def test_drop_targets_a_system_the_agent_will_write_to(monkeypatch):
    from chaos import injector
    monkeypatch.setattr(injector, "get_db", lambda: FakeDB(shipments=FakeColl([{"shipment_id": "S"}])))
    held = []
    monkeypatch.setattr(injector.httpx, "get", lambda url, **kw: types.SimpleNamespace(json=lambda: held))
    assert injector._drop_target() == "warehouse"
    held.append({"reservation_id": "RES-1"})
    assert injector._drop_target() == "hospital"


def test_wake_waits_for_a_live_agent_then_starts_a_fresh_one(monkeypatch):
    import subprocess
    from datetime import datetime, timezone
    from chaos import injector
    live = subprocess.Popen(["sleep", "0.3"])
    worker = {"pid": live.pid, "worker_id": "w7", "heartbeat": datetime.now(timezone.utc), "alive": True}
    monkeypatch.setattr(injector, "get_db", lambda: FakeDB(
        workers=FakeColl([worker]), shipments=FakeColl([{"shipment_id": "S"}])))
    started = []
    monkeypatch.setattr(injector, "_start_agent", lambda shipment_id, worker_id="worker-1": started.append((shipment_id, worker_id)) or 99)
    assert injector.wake_agent() is None and started == []  # it is still working, so nothing starts yet
    assert injector.wake_agent() is None                     # a second press queues nothing more
    time.sleep(1.5)
    assert started == [("S", "w7")]

    # The agent died without signing off: Atlas still says alive and fresh, the process is gone. Start at once.
    assert injector.wake_agent() == 99 and len(started) == 2


def test_second_press_before_the_agent_registers_starts_no_second_agent(monkeypatch):
    import subprocess
    from chaos import injector
    monkeypatch.setattr(injector, "get_db", lambda: FakeDB(shipments=FakeColl([{"shipment_id": "S"}])))  # no worker yet
    real, spawned = subprocess.Popen, []
    def popen(argv, **k):
        spawned.append(argv)
        return real(["sleep", "0.4"])
    monkeypatch.setattr(injector.subprocess, "Popen", popen)
    assert injector.wake_agent() and injector.wake_agent() is None  # the first one is still starting up
    time.sleep(1.2)
    assert len(spawned) == 2, "the queued start runs once the first agent has exited"
