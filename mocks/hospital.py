"""Mock hospital receiving system. Owner: MOCKS. Contract: docs/CONTRACTS.md, section "Hospital"."""
from fastapi import HTTPException

from mocks.common import make_app

app = make_app("hospital")


@app.put("/deliveries/{shipment_id}")
def update_delivery(shipment_id: str, body: dict):
    raise HTTPException(501, "TODO(MOCKS): PUT is naturally idempotent, store eta and status")


@app.get("/deliveries/{shipment_id}")
def get_delivery(shipment_id: str):
    raise HTTPException(501, "TODO(MOCKS)")
