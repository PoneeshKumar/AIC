"""Backend for the demo screen. Owner: UI. Reads Atlas and the mocks, never talks to the agent directly.

GET  /            the demo screen
GET  /state       one JSON blob the page polls every second (shape: docs/CONTRACTS.md, "UI state")
POST /chaos/{e}   fire a chaos event
POST /approve     approve or correct a proposed fix

Every source is optional. If Atlas or a mock is down, /state still answers and says so,
so the screen never goes blank in front of a judge.
"""
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pymongo.errors import PyMongoError

from agent import adapt
from agent import memory
from agent import tracing
from core import config
from core.db import get_db
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


ATLAS_RETRY_S = 5
_atlas_retry_at = 0.0  # after a failed ping, skip Atlas until this monotonic time so /state stays fast


def _db():
    """Atlas handle, or None when there is no connection string or the cluster is unreachable."""
    global _atlas_retry_at
    if not config.MONGODB_URI or time.monotonic() < _atlas_retry_at:
        return None
    try:
        db = get_db()
        db.command("ping")
        return db
    except Exception:
        _atlas_retry_at = time.monotonic() + ATLAS_RETRY_S
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
    # bookings and reservations stay None when the read failed, so "unknown" is never shown as 0
    return {"up": up, "tracking": tracking, "bookings": bookings,
            "reservations": reservations, "delivery": delivery}


def _duplicates(world: dict) -> int | None:
    """Same rule as chaos.invariants.duplicate_actions, applied to the reads /state already made.

    One intended action is a distinct (warehouse, window) for storage or a distinct route for a booking.
    Counting here keeps /state to one round of reads, and it never depends on Atlas or on fixed mock ports.
    Returns None when either list could not be read, because a count of what we cannot see would be a guess.
    """
    if world["reservations"] is None or world["bookings"] is None:
        return None
    holds = Counter((r.get("warehouse_id"), r.get("from"), r.get("to")) for r in world["reservations"])
    books = Counter(b.get("route_id") for b in world["bookings"])
    return sum(n - 1 for n in (*holds.values(), *books.values()))


def _atlas(db, shipment_id: str) -> dict:
    """Shipment, latest run, steps, events, worker and pending proposal from Atlas."""
    ship = db[config.SHIPMENTS].find_one({"shipment_id": shipment_id}, {"_id": 0}) or {}
    run = db[config.RUNS].find_one({"shipment_id": shipment_id}, sort=[("_id", -1)])
    run_id = (run or {}).get("run_id") or (str(run["_id"]) if run else None)
    steps = list(db[config.STEPS].find({"run_id": run_id}, {"_id": 0}).sort("seq", 1)) if run_id else []
    events = list(db[config.EVENTS].find({"run_id": run_id}).sort("ts", -1).limit(40)) if run_id else []
    worker = db[config.WORKERS].find_one({}, sort=[("heartbeat", -1)])
    proposal = db["proposals"].find_one({"status": "pending"}, sort=[("_id", -1)])
    return {"ship": ship, "run": run, "steps": steps, "events": list(reversed(events)), "worker": worker, "proposal": proposal}


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
    try:
        atlas = _atlas(db, shipment_id) if db is not None else None
    except PyMongoError:  # Atlas answered the ping and then failed, so show the mocks only
        atlas = None
    run = (atlas or {}).get("run") or {}
    log = []

    if atlas is None:
        ship = {"status": seeded.get("status", "unknown"), "budget_remaining_min": seeded["excursion_budget_minutes"]}
        steps, worker, proposal = [], None, None
        log += [{"ts": _clock(ts), "message": m} for ts, m in _local_chaos[-20:]]
        log.append({"ts": _clock(datetime.now(timezone.utc)), "message": "Atlas is not connected. Showing the mock systems only."})
    else:
        ship, steps, worker, proposal = atlas["ship"], atlas["steps"], atlas["worker"], atlas["proposal"]
        ship = {**ship, **_run_view(run)}
        log += [{"ts": _clock(e.get("ts")), "message": e.get("message", "")} for e in atlas["events"]]

    tracking = world["tracking"] or {}
    return {
        "shipment": {
            "shipment_id": shipment_id,
            "status": ship.get("status", seeded.get("status")),
            "budget_remaining_min": ship.get("budget_remaining_min", seeded["excursion_budget_minutes"]),
        },
        "counters": {
            "duplicate_actions": _duplicates(world),
            "steps_verified": sum(1 for s in steps if s.get("status") == "verified"),
            "steps_total": len(steps),
        },
        "steps": [{k: s.get(k) for k in ("seq", "action", "system", "status", "reason")} for s in steps],
        "systems": {
            "carrier": {"ok": world["up"]["carrier"], "schema_version": 2 if "tracking" in tracking else 1},
            "warehouse": {"ok": world["up"]["warehouse"], "reservations": None if world["reservations"] is None else len(world["reservations"])},
            "hospital": {"ok": world["up"]["hospital"]},
            "agent": {"worker": (worker or {}).get("worker_id"), "alive": _alive(worker)},
        },
        "proposal": _proposal_view(proposal),
        "log": log,
        "trace_url": tracing.trace_url(run.get("trace_id")) if atlas else None,
    }


def _run_view(run: dict) -> dict:
    """Shipment status and budget as the agent recorded them on the run. Only the seed writes the shipment document."""
    view = {}
    status = run.get("status")
    if status == "complete":
        view["status"] = "recovered"
    elif status == "blocked":
        view["status"] = run.get("blocked_reason") or "quarantined"  # no feasible route means it stays quarantined
    elif status:
        view["status"] = status
    if run.get("budget_after_minutes") is not None:
        view["budget_remaining_min"] = run["budget_after_minutes"]
    return view


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
    # Shape written by agent.adapt.propose_fix: the draft is under "proposal", the recalled memories under "matches".
    draft, top = p.get("proposal") or {}, (p.get("matches") or [{}])[0]
    return {"proposal_id": p.get("proposal_id"), "system": (p.get("failure") or {}).get("system"),
            "summary": draft.get("summary", ""), "fix": draft.get("fix", {}),
            "memory_hit": top.get("summary"), "score": top.get("score")}


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
        call("carrier", "POST", "/admin/cancel_flight", json={"flight": flight}).raise_for_status()
        return {"event": event, "message": f"Flight {flight} cancelled"}
    if event == "change_carrier":
        call("carrier", "POST", "/admin/schema", json={"version": 2}).raise_for_status()
        return {"event": event, "message": "Carrier switched to its new API format"}
    if event == "drop_response":
        call("warehouse", "POST", "/admin/faults", json={"drop_next_responses": 1}).raise_for_status()
        return {"event": event, "message": "The warehouse will drop its next response"}
    raise HTTPException(501, f"{event} needs the chaos injector, which is not built yet")


@app.post("/chaos/{event}")
def chaos(event: str):
    if event not in CHAOS_EVENTS:
        raise HTTPException(404, f"unknown chaos event {event}")
    if _db() is None:  # the real injector logs to Atlas, so without it use the mock admin calls directly
        try:
            return _fallback_fire(event)
        except httpx.HTTPStatusError as e:
            raise HTTPException(502, f"A mock system refused the chaos call with {e.response.status_code}")
        except httpx.HTTPError:
            raise HTTPException(503, "Could not reach the mock systems. Are they running?")
    from chaos.injector import fire, random_run
    try:
        if event == "random":
            first = random_run(seed=int(datetime.now().timestamp()), count=1)[0]
            if "message" not in first:
                raise HTTPException(502, "Random chaos failed: " + first.get("error", "unknown"))
            return {"event": event, "message": first["message"]}
        return fire(event)
    except HTTPException:
        raise
    except httpx.HTTPStatusError as e:  # a mock answered and said no
        raise HTTPException(502, f"{event} failed: {e}")
    except (httpx.HTTPError, PyMongoError) as e:  # a mock or Atlas is unreachable
        raise HTTPException(503, f"{event} failed: {e}")
    except RuntimeError as e:  # nothing to act on, for example no live worker to kill
        raise HTTPException(409, f"{event} failed: {e}")
    except Exception as e:
        raise HTTPException(500, f"{event} failed: {e}")


def _wake_agent() -> None:
    """The run was blocked on this approval, so start the agent to finish it. The rule is stored either way."""
    try:
        from chaos.injector import wake_agent
        wake_agent()
    except Exception:
        pass


@app.post("/approve")
def approve(body: dict):
    """Body: {proposal_id, action|decision, rule|fix, approved_by|by}."""
    proposal_id = body.get("proposal_id")
    if not proposal_id:
        raise HTTPException(400, "proposal_id and action (approve or correct) are required")

    db = _db()
    if db is None:
        raise HTTPException(503, "Atlas is not connected, so there is nothing to approve")

    action = body.get("action") or body.get("decision")
    if action in {"approved", "approve"}:
        action = "approve"
    elif action in {"corrected", "correct"}:
        action = "correct"
    else:
        raise HTTPException(400, "proposal_id and action (approve or correct) are required")

    rule = body.get("rule") or body.get("fix")
    try:
        resolved = adapt.resolve_proposal(
            db, proposal_id, action, rule, body.get("approved_by") or body.get("by") or "human"
        )
        _wake_agent()
        return resolved
    except adapt.ProposalNotFound as exc:
        raise HTTPException(404, f"proposal not found: {proposal_id}") from exc
    except adapt.ProposalResolved as exc:
        raise HTTPException(409, f"proposal already resolved: {proposal_id}") from exc
    except memory.MemorySuperseded as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # Atlas, a missing key or the Voyage SDK, whose errors share no base class with the others
        raise HTTPException(502, f"could not store the rule: {exc}") from exc
