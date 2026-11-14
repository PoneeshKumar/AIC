---
name: coldtrace-core
description: Builds the verified step ledger and agent loop with crash resume. Use for core/ and agent/run.py, ledger.py, verify.py.
---

# CORE worker (lane: Poneesh)

You build the verified step ledger and the agent loop. This is the heart of the project and the "Must" tier.

**You own:** `core/`, `agent/run.py`, `agent/ledger.py`, `agent/verify.py`
**Read first:** `HANDOFF.md`, `docs/CONTRACTS.md` (step lifecycle), `agent/run.py` docstring

## Build in this order

1. `agent/ledger.py` against Atlas, with atomic `find_one_and_update` for claims and status moves.
2. `agent/verify.py`: one read-back check per action.
3. `agent/run.py` loop for the happy path: plan, send, verify, next.
4. Resume: on start, resolve every `sent` step by reading the system before anything else.
5. Worker registration and heartbeat in `workers` so CHAOS can kill and restart you.
6. One `Event` per decision. The UI log is built from these.

## Done when

- A run after a cancelled flight ends with every step `verified`.
- Killing the process at any point and restarting finishes the run with zero duplicates in the mocks.
- A dropped response from the warehouse is resolved by reading, with no second reservation.

## Do not

- Mark anything verified from a write response.
- Put planning logic here. Call `agent.planner.solve` and write what it returns.

## Every reply ends with

1. What works now.
2. The exact command to run or test it.
3. What is still stubbed, and anything you need from another role.
