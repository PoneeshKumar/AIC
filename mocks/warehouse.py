"""Mock cold storage network. Owner: MOCKS. Contract: docs/CONTRACTS.md, section "Warehouse"."""
from fastapi import HTTPException

from mocks.common import make_app, seed

app = make_app("warehouse")


def _wh() -> dict:
    return app.state.store.setdefault("wh", {w["warehouse_id"]: dict(w) for w in seed("warehouses.json")["warehouses"]})


def _res() -> list:
    return app.state.store.setdefault("res", [])


@app.get("/capacity")
def capacity(city: str):
    held = [r["warehouse_id"] for r in _res()]
    return [{**w, "bays_free": w["bays_free"] - held.count(w["warehouse_id"])} for w in _wh().values() if w["city"] == city]


@app.post("/reservations")
def reserve(body: dict):
    wh = _wh().get(body.get("warehouse_id"))
    if not wh or not body.get("shipment_id"):
        raise HTTPException(422, "need shipment_id and a known warehouse_id")
    if wh["bays_free"] - [r["warehouse_id"] for r in _res()].count(wh["warehouse_id"]) <= 0:
        raise HTTPException(409, "no bays free")
    r = {"reservation_id": f"RES-{len(_res()) + 1}", **{k: body.get(k) for k in ("shipment_id", "warehouse_id", "from", "to")}}
    _res().append(r)
    return r


@app.get("/reservations")
def list_reservations(shipment_id: str):
    return [r for r in _res() if r["shipment_id"] == shipment_id]
