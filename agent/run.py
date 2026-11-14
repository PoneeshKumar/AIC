"""Run the verified ColdTrace recovery loop."""
from __future__ import annotations

import argparse
import os
import uuid
from datetime import datetime, timezone

import httpx

from agent import adapt, ledger, memory, planner, tracing, verify
from core import config
from core.db import ensure_indexes, get_db
from core.models import Event, Step


def _now() -> datetime:
  return datetime.now(timezone.utc)


def _event(db, run_id: str, worker_id: str, kind: str, message: str, data: dict | None = None) -> None:
  db[config.EVENTS].insert_one(Event(
    run_id=run_id,
    worker=worker_id,
    kind=kind,
    message=message,
    data=data or {},
  ).model_dump())


def _register_worker(db, worker_id: str) -> None:
  db[config.WORKERS].update_one(
    {"worker_id": worker_id},
    {"$set": {"worker_id": worker_id, "pid": os.getpid(), "heartbeat": _now(), "alive": True}},
    upsert=True,
  )


def _heartbeat(db, worker_id: str) -> None:
  db[config.WORKERS].update_one(
    {"worker_id": worker_id},
    {"$set": {"heartbeat": _now(), "alive": True}},
  )


def _load_run(db, shipment_id: str) -> dict:
  run = db[config.RUNS].find_one(
    {"shipment_id": shipment_id, "$or": [
      {"status": {"$in": ["running", "recovering"]}},
      {"status": "blocked", "blocked_reason": "waiting_approval"},
    ]},
    sort=[("created_at", -1)],
  )
  if run:
    return run
  run = {
    "run_id": str(uuid.uuid4()),
    "shipment_id": shipment_id,
    "status": "recovering",
    "created_at": _now(),
    "updated_at": _now(),
  }
  db[config.RUNS].insert_one(run)
  return run


def _response_items(response: httpx.Response, key: str) -> list[dict]:
  response.raise_for_status()
  payload = response.json()
  return payload if isinstance(payload, list) else payload.get(key, [])


def _available_warehouse(route: dict) -> str | None:
  for leg in route.get("legs", []):
    city = leg.get("layover_city")
    if not city:
      continue
    response = httpx.get(
      f"{config.WAREHOUSE_URL}/capacity", params={"city": city}, timeout=10
    )
    response.raise_for_status()
    payload = response.json()
    warehouses = payload if isinstance(payload, list) else payload.get("warehouses", [])
    for warehouse in warehouses:
      if warehouse.get("qualified_2_8c") and warehouse.get("bays_free", 0) > 0:
        return warehouse["warehouse_id"]
  return None


def _route_options(shipment: dict) -> list[planner.RouteOption]:
  response = httpx.get(
    f"{config.CARRIER_URL}/routes",
    params={"origin": shipment["origin"], "dest": shipment["destination"]},
    timeout=10,
  )
  routes = _response_items(response, "routes")
  options = []
  for route in routes:
    warehouse_id = _available_warehouse(route)
    uncooled = sum(
      leg.get("duration_min", 0)
      for leg in route.get("legs", [])
      if not leg.get("cooled", False)
    )
    if warehouse_id:
      uncooled = 0
    options.append(planner.RouteOption(
      route_id=route["route_id"],
      legs=route.get("legs", []),
      warehouse_id=warehouse_id,
      uncooled_minutes=uncooled,
    ))
  return options


def _world_state(shipment_id: str) -> dict:
  """What the warehouse and the carrier already hold for this shipment.

  A new run gets a new run_id, so its idempotency keys are new too. Reading the world first is what
  stops a second start from reserving and booking again. A failed read raises, so we never plan blind.
  """
  query = {"shipment_id": shipment_id}
  reservations = _response_items(
    httpx.get(f"{config.WAREHOUSE_URL}/reservations", params=query, timeout=10), "reservations"
  )
  bookings = _response_items(
    httpx.get(f"{config.CARRIER_URL}/bookings", params=query, timeout=10), "bookings"
  )
  return {
    "reservation": reservations[-1] if reservations else None,
    "booking": bookings[-1] if bookings else None,
  }


def _verified_state(db, run_id: str, shipment_id: str) -> dict:
  state = {"run_id": run_id, "shipment_id": shipment_id, **_world_state(shipment_id)}
  for step in db[config.STEPS].find({"run_id": run_id, "status": "verified"}).sort("seq", 1):
    evidence = step.get("evidence") or {}
    if step.get("action") == "reserve_storage":
      state["reservation"] = evidence.get("matched")
    elif step.get("action") == "rebook_carrier":
      state["booking"] = evidence.get("matched")
  return state


def _step_system(action: str) -> str:
  return {
    "set_quarantine": "hospital",
    "notify_hospital": "hospital",
    "reserve_storage": "warehouse",
    "rebook_carrier": "carrier",
  }[action]


def _send(step: Step) -> None:
  headers = {"Idempotency-Key": step.idempotency_key}
  if step.action in {"set_quarantine", "notify_hospital"}:
    response = httpx.put(
      f"{config.HOSPITAL_URL}/deliveries/{step.request['shipment_id']}",
      json=step.request, headers=headers, timeout=10,
    )
  elif step.action == "reserve_storage":
    response = httpx.post(
      f"{config.WAREHOUSE_URL}/reservations",
      json=step.request, headers=headers, timeout=10,
    )
  elif step.action == "rebook_carrier":
    response = httpx.post(
      f"{config.CARRIER_URL}/bookings",
      json=step.request, headers=headers, timeout=10,
    )
  else:
    raise ValueError(f"unsupported action: {step.action}")
  response.raise_for_status()


@tracing.traced("resume_sent")
def _resume_sent(db, run_id: str, worker_id: str) -> None:
  for step in ledger.unresolved_sent_steps(run_id):
    took_effect, evidence = verify.verify(step)
    if took_effect:
      ledger.mark_verified(step, evidence, f"GET read-back for {step.action}")
      _event(db, run_id, worker_id, "resume", f"resume verified {step.action}", evidence)
    else:
      ledger.mark_failed(step, evidence)
      _event(db, run_id, worker_id, "resume", f"resume found no effect for {step.action}", evidence)


@tracing.traced("plan_if_needed")
def _plan_if_needed(db, run: dict, shipment: dict, worker_id: str) -> None:
  run_id = run["run_id"]
  statuses = {step["status"] for step in db[config.STEPS].find({"run_id": run_id})}
  if "sent" in statuses:
    return
  if "planned" in statuses:
    if "failed" not in statuses:
      return
    # A step failed, so the rest of the old plan no longer holds. Drop it and plan again from verified state.
    skipped = ledger.skip_planned(run_id)
    _event(db, run_id, worker_id, "plan", f"a step failed, skipped {skipped} planned steps to re-plan")
  plan = planner.solve(
    shipment["excursion_budget_minutes"],
    _route_options(shipment),
    _verified_state(db, run_id, shipment["shipment_id"]),
  )
  steps = [Step(
    run_id=run_id,
    seq=seq,
    action=item["action"],
    system=_step_system(item["action"]),
    idempotency_key=item["idempotency_key"],
    request=item["request"],
    reason=item["reason"],
    authorized_by=worker_id,
  ) for seq, item in enumerate(plan.steps, start=1)]
  ledger.write_plan(run_id, steps)
  db[config.RUNS].update_one(
    {"run_id": run_id},
    {"$set": {
      "status": "blocked" if plan.chosen.route_id == "no-feasible-route" else "recovering",
      "chosen_route_id": plan.chosen.route_id,
      "budget_after_minutes": plan.budget_after_minutes,
      "updated_at": _now(),
    }},
  )
  _event(db, run_id, worker_id, "plan", f"planned {len(steps)} recovery steps", {
    "route_id": plan.chosen.route_id,
    "budget_after_minutes": plan.budget_after_minutes,
    "rejected": plan.rejected,
  })


def _shape(value):
  """Field names and nesting only, so the failure signature ignores per-shipment values."""
  if isinstance(value, dict):
    return {key: _shape(item) for key, item in sorted(value.items())}
  return type(value).__name__


@tracing.traced("parse_carrier_status")
def parse_carrier_status(db, run_id: str, worker_id: str, shipment_id: str) -> dict | None:
  """Return the normalized carrier status, or None when the run must wait for a human.

  Schema v1 parses directly. Anything else tries approved rules first, then proposes a fix and stops.
  """
  response = httpx.get(f"{config.CARRIER_URL}/shipments/{shipment_id}", timeout=10)
  response.raise_for_status()
  raw = response.json()
  if "shipment_status" in raw and "eta" in raw:
    return {"shipment_status": raw["shipment_status"], "eta": raw["eta"]}

  for rule in memory.find_approved_rules("carrier"):
    try:
      translated = adapt.apply_rule(rule["fix"], raw)
    except (KeyError, ValueError, TypeError, AttributeError, OSError, OverflowError):
      continue
    _event(db, run_id, worker_id, "memory_hit", "applied stored carrier rule, no approval needed", {
      "memory_id": rule["_id"], "translated": translated,
    })
    return translated

  failure = {
    "system": "carrier",
    "endpoint": "GET /shipments/{id}",
    "expected": ["eta", "shipment_status"],
    "got": _shape(raw),
  }
  proposal = adapt.propose_fix(failure)
  if not db[config.EVENTS].find_one({"run_id": run_id, "data.proposal_id": proposal["proposal_id"]}):
    matches = proposal.get("matches") or []
    if matches:
      _event(db, run_id, worker_id, "memory_hit",
             f"memory hit ({float(matches[0].get('score', 0)):.2f}) for carrier drift", {
               "proposal_id": proposal["proposal_id"], "memory_id": matches[0].get("_id"),
               "score": matches[0].get("score"),
             })
    _event(db, run_id, worker_id, "proposal", "carrier response changed, waiting for human approval", {
      "proposal_id": proposal["proposal_id"], "fix": proposal["proposal"]["fix"],
    })
  db[config.RUNS].update_one({"run_id": run_id}, {"$set": {
    "status": "blocked", "blocked_reason": "waiting_approval", "updated_at": _now(),
  }})
  return None


@tracing.traced("recovery_run")
def run(shipment_id: str, worker_id: str = "worker-1") -> str:
  """Run one shipment recovery until it completes or needs a retry."""
  ensure_indexes()
  db = get_db()
  _register_worker(db, worker_id)
  shipment = db[config.SHIPMENTS].find_one({"shipment_id": shipment_id})
  if not shipment:
    raise ValueError(f"shipment not found: {shipment_id}")
  run_document = _load_run(db, shipment_id)
  run_id = run_document["run_id"]
  trace_id = tracing.current_run_id()
  if trace_id:
    db[config.RUNS].update_one({"run_id": run_id}, {"$set": {"trace_id": trace_id}})
  _event(db, run_id, worker_id, "start", f"started recovery for {shipment_id}")
  _resume_sent(db, run_id, worker_id)
  try:
    carrier_status = parse_carrier_status(db, run_id, worker_id, shipment_id)
  except httpx.HTTPError as exc:
    if run_document.get("blocked_reason") == "waiting_approval":
      # An unreadable carrier is not an approval. Stay blocked until the status parses.
      _event(db, run_id, worker_id, "finish", "carrier status read failed, still waiting for approval", {
        "error": str(exc),
      })
      return run_id
    _event(db, run_id, worker_id, "send", "carrier status read failed, continuing", {"error": str(exc)})
    carrier_status = {}
  if carrier_status is None:
    _event(db, run_id, worker_id, "finish", "recovery blocked: waiting for approval")
    return run_id
  db[config.RUNS].update_one({"run_id": run_id}, {"$set": {"carrier_status": carrier_status}})
  db[config.RUNS].update_one(
    {"run_id": run_id, "blocked_reason": "waiting_approval"},
    {"$set": {"status": "recovering", "updated_at": _now()}, "$unset": {"blocked_reason": ""}},
  )
  _plan_if_needed(db, run_document, shipment, worker_id)

  while True:
    _heartbeat(db, worker_id)
    step = ledger.next_step(run_id, worker_id)
    if step is None:
      break
    ledger.mark_sent(step)
    _event(db, run_id, worker_id, "send", f"sent {step.action}", {"seq": step.seq})
    try:
      _send(step)
    except Exception as exc:
      _event(db, run_id, worker_id, "send", f"request outcome unknown for {step.action}, reading back", {
        "error": str(exc), "seq": step.seq,
      })
    try:
      took_effect, evidence = verify.verify(step)
    except (httpx.HTTPError, ValueError) as exc:
      # The step stays `sent`, so the next start resolves it by reading.
      _event(db, run_id, worker_id, "verify", f"could not read back {step.action}", {
        "error": str(exc), "seq": step.seq,
      })
      break
    if took_effect:
      ledger.mark_verified(step, evidence, f"GET read-back for {step.action}")
      _event(db, run_id, worker_id, "verify", f"verified {step.action}", evidence)
    else:
      ledger.mark_failed(step, evidence)
      _event(db, run_id, worker_id, "verify", f"failed to verify {step.action}", evidence)
      break

  remaining = db[config.STEPS].count_documents({
    "run_id": run_id, "status": {"$nin": ["verified", "skipped"]},
  })
  total = db[config.STEPS].count_documents({"run_id": run_id})
  current_run = db[config.RUNS].find_one({"run_id": run_id}) or {}
  status = (
    "blocked"
    if current_run.get("status") == "blocked"
    else "complete" if total and remaining == 0 else "recovering"
  )
  db[config.RUNS].update_one(
    {"run_id": run_id}, {"$set": {"status": status, "updated_at": _now()}}
  )
  _event(db, run_id, worker_id, "finish", f"recovery {status}")
  return run_id


def main() -> None:
  parser = argparse.ArgumentParser()
  parser.add_argument("--shipment", required=True)
  parser.add_argument("--worker-id", default="worker-1")
  args = parser.parse_args()
  run_id = run(args.shipment, args.worker_id)
  if tracing.enabled():
    from chaos.invariants import check_all
    db = get_db()
    current_run = db[config.RUNS].find_one({"run_id": run_id}) or {}
    if current_run.get("status") == "complete" and current_run.get("trace_id"):
      try:
        results = check_all(run_id, args.shipment)
        tracing.score(current_run["trace_id"], {
          "duplicate_actions": results["duplicate_actions"] == 0,
          "ledger_matches_world": not results["ledger_mismatches"],
          "budget_respected": results["budget_respected"],
        })
      except Exception:
        tracing.log.warning("could not score completed run", exc_info=True)
    tracing.flush()


if __name__ == "__main__":
    main()
