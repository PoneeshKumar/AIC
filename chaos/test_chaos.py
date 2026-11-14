"""Smoke check: duplicates counter against the real mocks. Run: pytest chaos -q"""
import threading, time
import httpx, uvicorn
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
