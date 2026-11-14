"""Backend for the demo screen. Owner: UI. Reads Atlas, calls chaos, never talks to the agent directly.

GET  /            the demo screen
GET  /state       one JSON blob the page polls every second (shape: docs/CONTRACTS.md, "UI state")
POST /chaos/{e}   fire a chaos event
POST /approve     approve or correct a proposed fix
"""
from pathlib import Path
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pymongo.errors import PyMongoError

from chaos import invariants
from core import config
from core.db import get_db

app = FastAPI(title="ColdTrace")
UI = Path(__file__).resolve().parent.parent / "ui" / "index.html"


@app.get("/")
def index():
    return FileResponse(UI)


@app.get("/state")
def state():
    try:
        return _read_state()
    except PyMongoError as exc:
        raise HTTPException(
            status_code=503,
            detail="Atlas is unavailable. Check MONGODB_URI credentials in .env.",
        ) from exc


def _read_state():
    db = get_db()
    shipment = db[config.SHIPMENTS].find_one(sort=[("updated_at", -1), ("created_at", -1)]) or {}
    shipment_id = shipment.get("shipment_id")
    run = (
        db[config.RUNS].find_one({"shipment_id": shipment_id}, sort=[("created_at", -1)])
        if shipment_id
        else None
    ) or {}
    run_id = run.get("run_id")
    steps = list(db[config.STEPS].find({"run_id": run_id}, {"_id": 0}).sort("seq", 1)) if run_id else []
    events = list(db[config.EVENTS].find({"run_id": run_id}, {"_id": 0}).sort("ts", -1).limit(30)) if run_id else []
    workers = list(db[config.WORKERS].find({}, {"_id": 0}).sort("heartbeat", -1))
    proposal = db[config.PROPOSALS].find_one(
        {"status": "pending"}, {"_id": 0}, sort=[("created_at", -1)]
    )

    verified = sum(step.get("status") == "verified" for step in steps)
    systems = {
        "carrier": _health(config.CARRIER_URL),
        "warehouse": _health(config.WAREHOUSE_URL),
        "hospital": _health(config.HOSPITAL_URL),
        "agent": _agent_health(workers),
    }
    current = {
        "shipment_id": shipment_id,
        "status": run.get("status", "idle"),
        "budget_remaining_min": run.get(
            "budget_after_minutes", shipment.get("excursion_budget_minutes", 0)
        ),
    }
    return {
        "shipment": current,
        "counters": {
            "duplicate_actions": invariants.duplicate_actions(shipment_id) if shipment_id else 0,
            "steps_verified": verified,
            "steps_total": len(steps),
        },
        "steps": [_state_step(step) for step in steps],
        "systems": systems,
        "proposal": proposal,
        "log": [_state_event(event) for event in reversed(events)],
    }


def _health(base_url: str) -> dict:
    try:
        response = httpx.get(f"{base_url}/health", timeout=0.5)
        response.raise_for_status()
        return {"ok": bool(response.json().get("ok"))}
    except httpx.HTTPError:
        return {"ok": False}


def _agent_health(workers: list[dict]) -> dict:
    worker = workers[0] if workers else None
    if not worker:
        return {"worker": None, "alive": False}
    heartbeat = worker.get("heartbeat")
    alive = bool(worker.get("alive"))
    if isinstance(heartbeat, datetime):
        alive = alive and (datetime.now(timezone.utc) - heartbeat).total_seconds() < 30
    return {"worker": worker.get("worker_id"), "alive": alive}


def _state_step(step: dict) -> dict:
    return {
        "seq": step.get("seq"),
        "action": step.get("action"),
        "system": step.get("system"),
        "status": step.get("status"),
        "reason": step.get("reason", ""),
    }


def _state_event(event: dict) -> dict:
    timestamp = event.get("ts")
    return {
        "ts": timestamp.isoformat() if isinstance(timestamp, datetime) else timestamp,
        "message": event.get("message", ""),
    }


@app.post("/chaos/{event}")
def chaos(event: str):
    raise HTTPException(501, "TODO(UI): call chaos.injector.fire(event)")


@app.post("/approve")
def approve(body: dict):
    raise HTTPException(501, "TODO(UI): mark the proposal approved or corrected")
