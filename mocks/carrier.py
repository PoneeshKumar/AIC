"""Mock carrier. Owner: MOCKS. Contract: docs/CONTRACTS.md, section "Carrier"."""
from fastapi import HTTPException

from mocks.common import make_app

app = make_app("carrier")
app.state.schema_version = 1  # flipped to 2 by the "Change carrier API" chaos button


@app.get("/shipments/{shipment_id}")
def get_shipment(shipment_id: str):
    # v1: {"shipment_status": "delayed", "eta": "2026-11-14T18:00:00Z"}
    # v2: {"tracking": {"state": "DISRUPTED", "estimated_arrival_epoch": 1794688800}}
    raise HTTPException(501, "TODO(MOCKS)")


@app.get("/routes")
def list_routes(origin: str, dest: str):
    raise HTTPException(501, "TODO(MOCKS): serve data/seed/routes.json minus cancelled flights")


@app.post("/bookings")
def create_booking(body: dict):
    raise HTTPException(501, "TODO(MOCKS): idempotent on the Idempotency-Key header")


@app.get("/bookings")
def list_bookings(shipment_id: str):
    raise HTTPException(501, "TODO(MOCKS): the read the agent uses to verify a booking")


@app.post("/admin/cancel_flight")
def cancel_flight(body: dict):
    raise HTTPException(501, "TODO(MOCKS)")


@app.post("/admin/schema")
def set_schema(body: dict):
    app.state.schema_version = int(body.get("version", 1))
    return {"schema_version": app.state.schema_version}
