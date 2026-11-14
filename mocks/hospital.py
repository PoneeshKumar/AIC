"""Mock hospital receiving system. Owner: MOCKS. Contract: docs/CONTRACTS.md, section "Hospital"."""
from fastapi import HTTPException

from mocks.common import make_app

app = make_app("hospital")


@app.put("/deliveries/{shipment_id}")
def update_delivery(shipment_id: str, body: dict):
    d = app.state.store.setdefault("deliveries", {})
    d[shipment_id] = {"shipment_id": shipment_id, "eta": body.get("eta"), "status": body.get("status")}
    return d[shipment_id]


@app.get("/deliveries/{shipment_id}")
def get_delivery(shipment_id: str):
    d = app.state.store.get("deliveries", {}).get(shipment_id)
    if not d:
        raise HTTPException(404, "no delivery record")
    return d
