"""Mock cold storage network. Owner: MOCKS. Contract: docs/CONTRACTS.md, section "Warehouse"."""
from fastapi import HTTPException

from mocks.common import make_app

app = make_app("warehouse")


@app.get("/capacity")
def capacity(city: str):
    raise HTTPException(501, "TODO(MOCKS): serve data/seed/warehouses.json")


@app.post("/reservations")
def reserve(body: dict):
    raise HTTPException(501, "TODO(MOCKS): idempotent on the Idempotency-Key header")


@app.get("/reservations")
def list_reservations(shipment_id: str):
    raise HTTPException(501, "TODO(MOCKS): feeds the 'duplicate actions' counter")
