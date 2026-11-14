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
    worker = {"pid": victim.pid, "worker_id": "w7", "heartbeat": now}
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
