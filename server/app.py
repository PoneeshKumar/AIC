"""Backend for the demo screen. Owner: UI. Reads Atlas, calls chaos, never talks to the agent directly.

GET  /            the demo screen
GET  /state       one JSON blob the page polls every second (shape: docs/CONTRACTS.md, "UI state")
POST /chaos/{e}   fire a chaos event
POST /approve     approve or correct a proposed fix
"""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

app = FastAPI(title="ColdTrace")
UI = Path(__file__).resolve().parent.parent / "ui" / "index.html"


@app.get("/")
def index():
    return FileResponse(UI)


@app.get("/state")
def state():
    raise HTTPException(501, "TODO(UI): assemble from shipments, steps, events, workers + chaos.invariants")


@app.post("/chaos/{event}")
def chaos(event: str):
    raise HTTPException(501, "TODO(UI): call chaos.injector.fire(event)")


@app.post("/approve")
def approve(body: dict):
    raise HTTPException(501, "TODO(UI): mark the proposal approved or corrected")
