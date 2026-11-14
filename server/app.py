"""Backend for the demo screen. Owner: UI. Reads Atlas and the mocks, never talks to the agent directly.

GET  /            the demo screen
GET  /state       one JSON blob the page polls every second (shape: docs/CONTRACTS.md, "UI state")
POST /chaos/{e}   fire a chaos event
POST /approve     approve or correct a proposed fix

Every source is optional. If Atlas or a mock is down, /state still answers and says so,
so the screen never goes blank in front of a judge.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from core import config
from mocks.common import seed

app = FastAPI(title="ColdTrace")
UI = Path(__file__).resolve().parent.parent / "ui"
app.mount("/ui", StaticFiles(directory=UI), name="ui")

# On Windows "localhost" tries IPv6 first and costs about 2 s per new connection, so use the IPv4 address.
URLS = {name: url.replace("localhost", "127.0.0.1") for name, url in
        {"carrier": config.CARRIER_URL, "warehouse": config.WAREHOUSE_URL, "hospital": config.HOSPITAL_URL}.items()}
HEARTBEAT_OK_S = 5
CHAOS_EVENTS = ["cancel_flight", "kill_agent", "change_carrier", "drop_response", "random"]
_http = httpx.Client(timeout=0.5)  # one pooled client, building one per call costs about 0.4 s


def call(system: str, method: str, path: str, **kw) -> httpx.Response:
    """One HTTP call to a mock. Tests replace this to talk to in-process apps."""
    return _http.request(method, URLS[system] + path, **kw)


def _read(system: str, path: str, **params):
    """GET that returns (ok, json or None) and never raises."""
    try:
        r = call(system, "GET", path, params=params)
        return True, (r.json() if r.status_code == 200 else None)
    except (httpx.HTTPError, ValueError):
        return False, None


def _db():
    """Atlas handle, or None when there is no connection string or the cluster is unreachable."""
    if not config.MONGODB_URI:
        return None
    try:
        from core.db import get_db
        db = get_db()
        db.command("ping")
        return db
    except Exception:
        return None


def _seed_shipment() -> dict:
    return seed("shipment.json")


def _clock(ts) -> str:
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.astimezone().strftime("%H:%M:%S")
    return str(ts or "")


def _world(shipment_id: str) -> dict:
    """What the other systems say right now. This is the truth the counters come from."""
    up = {s: _read(s, "/health")[0] for s in URLS}
    _, tracking = _read("carrier", f"/shipments/{shipment_id}")
    _, bookings = _read("carrier", "/bookings", shipment_id=shipment_id)
    _, reservations = _read("warehouse", "/reservations", shipment_id=shipment_id)
    _, delivery = _read("hospital", f"/deliveries/{shipment_id}")
    return {"up": up, "tracking": tracking, "bookings": bookings or [],
            "reservations": reservations or [], "delivery": delivery}


def _duplicates(shipment_id: str, world: dict) -> int:
    """Prefer the CHAOS invariant. Until it lands, count extra holds per warehouse and extra bookings."""
    try:
        from chaos.invariants import duplicate_actions
        return duplicate_actions(shipment_id)
    except NotImplementedError:
        per_wh = {}
        for r in world["reservations"]:
            per_wh[r.get("warehouse_id")] = per_wh.get(r.get("warehouse_id"), 0) + 1
        extra_holds = sum(n - 1 for n in per_wh.values() if n > 1)
        extra_bookings = max(0, len(world["bookings"]) - 1)
        return extra_holds + extra_bookings


def _atlas(db, shipment_id: str) -> dict:
    """Shipment, latest run, steps, events, worker and pending proposal from Atlas."""
    ship = db[config.SHIPMENTS].find_one({"shipment_id": shipment_id}, {"_id": 0}) or {}
    run = db[config.RUNS].find_one({"shipment_id": shipment_id}, sort=[("_id", -1)])
    run_id = (run or {}).get("run_id") or (str(run["_id"]) if run else None)
    steps = list(db[config.STEPS].find({"run_id": run_id}, {"_id": 0}).sort("seq", 1)) if run_id else []
    events = list(db[config.EVENTS].find({"run_id": run_id}).sort("ts", -1).limit(40)) if run_id else []
    worker = db[config.WORKERS].find_one({}, sort=[("heartbeat", -1)])
    proposal = db["proposals"].find_one({"status": "pending"}, sort=[("_id", -1)])
    return {"ship": ship, "steps": steps, "events": list(reversed(events)), "worker": worker, "proposal": proposal}


def _alive(worker) -> bool:
    beat = (worker or {}).get("heartbeat")
    if not isinstance(beat, datetime):
        return False
    if beat.tzinfo is None:
        beat = beat.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - beat < timedelta(seconds=HEARTBEAT_OK_S)


@app.get("/")
def index():
    return FileResponse(UI / "index.html")


@app.get("/state")
def state():
    seeded = _seed_shipment()
    shipment_id = seeded["shipment_id"]
    world = _world(shipment_id)
    db = _db()
    atlas = _atlas(db, shipment_id) if db is not None else None
    log = []

    if atlas is None:
        ship = {"status": seeded.get("status", "unknown"), "budget_remaining_min": seeded["excursion_budget_minutes"]}
        steps, worker, proposal = [], None, None
        log += [{"ts": _clock(ts), "message": m} for ts, m in _local_chaos[-20:]]
        log.append({"ts": _clock(datetime.now(timezone.utc)), "message": "Atlas is not connected. Showing the mock systems only."})
    else:
        ship, steps, worker, proposal = atlas["ship"], atlas["steps"], atlas["worker"], atlas["proposal"]
        log += [{"ts": _clock(e.get("ts")), "message": e.get("message", "")} for e in atlas["events"]]

    tracking = world["tracking"] or {}
    return {
        "shipment": {
            "shipment_id": shipment_id,
            "status": ship.get("status", seeded.get("status")),
            "budget_remaining_min": ship.get("budget_remaining_min", seeded["excursion_budget_minutes"]),
        },
        "counters": {
            "duplicate_actions": _duplicates(shipment_id, world),
            "steps_verified": sum(1 for s in steps if s.get("status") == "verified"),
            "steps_total": len(steps),
        },
        "steps": [{k: s.get(k) for k in ("seq", "action", "system", "status", "reason")} for s in steps],
        "systems": {
            "carrier": {"ok": world["up"]["carrier"], "schema_version": 2 if "tracking" in tracking else 1},
            "warehouse": {"ok": world["up"]["warehouse"], "reservations": len(world["reservations"])},
            "hospital": {"ok": world["up"]["hospital"]},
            "agent": {"worker": (worker or {}).get("worker_id"), "alive": _alive(worker)},
        },
        "proposal": _proposal_view(proposal),
        "log": log,
    }


# Airport coordinates for the map. Public reference positions, rounded.
AIRPORTS = {
    "YYZ": {"name": "Toronto", "lat": 43.678, "lon": -79.625},
    "YWG": {"name": "Winnipeg", "lat": 49.910, "lon": -97.240},
    "YYC": {"name": "Calgary", "lat": 51.122, "lon": -114.008},
    "YEG": {"name": "Edmonton", "lat": 53.310, "lon": -113.580},
    "YVR": {"name": "Vancouver", "lat": 49.195, "lon": -123.178},
}


@app.get("/network")
def network():
    """Routes, storage and what the carrier still offers, for the map and the route chart.

    Not part of /state on purpose: it changes rarely, so the page asks every few seconds.
    exposed_min is a display estimate (uncooled legs, minus layovers a free qualified bay could cover).
    The planner stays the authority on which route is chosen.
    """
    seeded = _seed_shipment()
    origin, dest = seeded["origin"], seeded["destination"]
    up, offered = _read("carrier", "/routes", origin=origin, dest=dest)
    offered_ids = {r["route_id"] for r in offered} if up and offered is not None else None
    _, bookings = _read("carrier", "/bookings", shipment_id=seeded["shipment_id"])
    booked = (bookings or [{}])[-1].get("route_id")

    routes, bays = [], {}
    for r in seed("routes.json")["routes"]:
        legs, exposed, total = [], 0, 0
        for leg in r["legs"]:
            kind = "layover" if "layover_city" in leg else ("truck" if "truck" in leg else "flight")
            covered = False
            if kind == "layover" and not leg["cooled"]:
                city = leg["layover_city"]
                if city not in bays:
                    _, cap = _read("warehouse", "/capacity", city=city)
                    bays[city] = sum(w["bays_free"] for w in (cap or []) if w.get("qualified_2_8c"))
                covered = bays[city] > 0
            if not leg["cooled"] and not covered:
                exposed += leg["duration_min"]
            total += leg["duration_min"]
            legs.append({"kind": kind, "flight": leg.get("flight"), "from": leg.get("from", leg.get("layover_city")),
                         "to": leg.get("to", leg.get("layover_city")), "duration_min": leg["duration_min"],
                         "cooled": leg["cooled"], "storage_covered": covered})
        status = "unknown" if offered_ids is None else ("booked" if r["route_id"] == booked else
                                                         "available" if r["route_id"] in offered_ids else "cancelled")
        routes.append({"route_id": r["route_id"], "legs": legs, "total_min": total, "exposed_min": exposed,
                       "status": status, "original": r["route_id"] == seeded["original_route_id"]})

    stops = {a for r in routes for l in r["legs"] for a in (l["from"], l["to"])}
    return {"origin": origin, "destination": dest, "booked_route_id": booked,
            "budget_total_min": seeded["excursion_budget_minutes"], "product": seeded.get("product"),
            "consignee": seeded.get("consignee"), "temp_range_c": seeded.get("temp_range_c"),
            "airports": {k: v for k, v in AIRPORTS.items() if k in stops},
            "storage": [{"city": c, "bays_free": n} for c, n in bays.items()], "routes": routes}


def _proposal_view(p):
    if not p:
        return None
    return {"proposal_id": str(p["_id"]), "system": p.get("system"), "summary": p.get("summary", ""),
            "fix": p.get("fix", {}), "memory_hit": p.get("memory_hit"), "score": p.get("score")}


_local_chaos = []  # (time, message) for fallback chaos, shown in the log only while Atlas is not connected


def _fallback_fire(event: str) -> dict:
    """Mock admin calls from docs/CONTRACTS.md, used only until chaos.injector.fire lands."""
    result = _fallback_call(event)
    _local_chaos.append((datetime.now(timezone.utc), "Chaos: " + result["message"]))
    return result


def _fallback_call(event: str) -> dict:
    if event == "cancel_flight":
        route_id = _seed_shipment()["original_route_id"]
        route = next(r for r in seed("routes.json")["routes"] if r["route_id"] == route_id)
        flight = next(l["flight"] for l in route["legs"] if "flight" in l)
        call("carrier", "POST", "/admin/cancel_flight", json={"flight": flight})
        return {"event": event, "message": f"Flight {flight} cancelled"}
    if event == "change_carrier":
        call("carrier", "POST", "/admin/schema", json={"version": 2})
        return {"event": event, "message": "Carrier switched to its new API format"}
    if event == "drop_response":
        call("warehouse", "POST", "/admin/faults", json={"drop_next_responses": 1})
        return {"event": event, "message": "The warehouse will drop its next response"}
    raise HTTPException(501, f"{event} needs the chaos injector, which is not built yet")


@app.post("/chaos/{event}")
def chaos(event: str):
    if event not in CHAOS_EVENTS:
        raise HTTPException(404, f"unknown chaos event {event}")
    try:
        from chaos.injector import fire, random_run
        result = random_run(seed=int(datetime.now().timestamp()), count=1) if event == "random" else fire(event)
        return {"event": event, "result": result}
    except NotImplementedError:
        try:
            return _fallback_fire(event)
        except httpx.HTTPError:
            raise HTTPException(503, "Could not reach the mock systems. Are they running?")


@app.post("/approve")
def approve(body: dict):
    """Body: {proposal_id, decision: "approved" | "corrected", fix (only when corrected), by}."""
    from bson import ObjectId
    from bson.errors import InvalidId

    decision = body.get("decision", "approved")
    if decision not in ("approved", "corrected"):
        raise HTTPException(422, "decision must be approved or corrected")
    db = _db()
    if db is None:
        raise HTTPException(503, "Atlas is not connected, so there is nothing to approve")
    try:
        pid = ObjectId(body.get("proposal_id"))
    except (InvalidId, TypeError):
        raise HTTPException(422, "proposal_id is not valid")
    update = {"status": decision, "approved_by": body.get("by", "human"), "decided_at": datetime.now(timezone.utc)}
    if decision == "corrected":
        update["fix"] = body.get("fix") or {}
    res = db["proposals"].update_one({"_id": pid, "status": "pending"}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(409, "no pending proposal with that id")
    return {"proposal_id": str(pid), "status": decision}
