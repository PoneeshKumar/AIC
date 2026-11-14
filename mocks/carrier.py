"""Mock carrier. Owner: MOCKS. Contract: docs/CONTRACTS.md, section "Carrier"."""
from fastapi import HTTPException

from mocks.common import make_app, seed

app = make_app("carrier")

ETA_ISO, ETA_EPOCH = "2026-11-14T18:00:00Z", 1794679200  # same instant, two formats


def _s() -> dict:
    return app.state.store.setdefault("c", {"schema": 1, "cancelled": set(), "bookings": []})


@app.get("/shipments/{shipment_id}")
def get_shipment(shipment_id: str):
    if shipment_id != seed("shipment.json")["shipment_id"]:
        raise HTTPException(404, "unknown shipment")
    if _s()["schema"] == 2:
        return {"tracking": {"state": "DISRUPTED", "estimated_arrival_epoch": ETA_EPOCH}}
    return {"shipment_status": "delayed", "eta": ETA_ISO}


def _flights(route: dict) -> set:
    return {l["flight"] for l in route["legs"] if "flight" in l}


def _available() -> list:
    return [r for r in seed("routes.json")["routes"] if not _flights(r) & _s()["cancelled"]]


@app.get("/routes")
def list_routes(origin: str, dest: str):
    ends = lambda r: [l for l in r["legs"] if "from" in l]
    return [r for r in _available() if ends(r)[0]["from"] == origin and ends(r)[-1]["to"] == dest]


@app.post("/bookings")
def create_booking(body: dict):
    if not body.get("shipment_id") or body.get("route_id") not in {r["route_id"] for r in _available()}:
        raise HTTPException(422, "need shipment_id and a route that is still available")
    b = {"booking_id": f"BK-{len(_s()['bookings']) + 1}", "shipment_id": body["shipment_id"],
         "route_id": body["route_id"], "status": "confirmed"}
    _s()["bookings"].append(b)
    return b


@app.get("/bookings")
def list_bookings(shipment_id: str):
    return [b for b in _s()["bookings"] if b["shipment_id"] == shipment_id]


@app.post("/admin/cancel_flight")
def cancel_flight(body: dict):
    _s()["cancelled"].add(body["flight"])
    return {"cancelled": sorted(_s()["cancelled"])}


@app.post("/admin/schema")
def set_schema(body: dict):
    _s()["schema"] = int(body.get("version", 1))
    return {"schema_version": _s()["schema"]}
