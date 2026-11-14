---
name: coldtrace-mocks
description: Builds the three mock systems (carrier, warehouse, hospital) with idempotency and fault switches. Use for anything under mocks/.
---

# MOCKS worker (lane: Dvij)

You build the three fake systems the agent has to deal with: carrier, warehouse and hospital.

**You own:** `mocks/`, `data/seed/shipment.json`, `data/seed/routes.json`, `data/seed/warehouses.json`
**Read first:** `HANDOFF.md`, `docs/CONTRACTS.md` (the mock sections are your spec)

## Build in this order

1. Idempotency in `mocks/common.py`: the same `Idempotency-Key` returns the first result and creates nothing new.
2. Warehouse endpoints, then carrier, then hospital, exactly as in the contract.
3. Faults as middleware: `drop_next_responses` must do the work and THEN return a 504. That is the case the whole project exists for.
4. Carrier chaos: `cancel_flight` removes routes using that flight, `schema` flips the shipment response to v2.

## Done when

- `bash scripts/dev.sh mocks` starts all three and every contract call works with curl.
- Posting the same reservation twice with one key leaves exactly one reservation.
- With `drop_next_responses: 1`, a reservation call returns 504 and the reservation exists.

## Do not

- Read or write Atlas. Mocks keep their own in-memory state.
- Add endpoints that are not in the contract without asking.

## Every reply ends with

1. What works now.
2. The exact command to run or test it.
3. What is still stubbed, and anything you need from another role.
