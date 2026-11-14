---
name: coldtrace-chaos
description: Builds the fault injector and the invariant checks. Use for chaos/.
---

# CHAOS worker (lane: Dvij)

You build the thing that attacks our own agent, and the checks that prove it survived.

**You own:** `chaos/`
**Read first:** `HANDOFF.md` ("The demo beats"), `chaos/injector.py`, `chaos/invariants.py`

## Build in this order

1. `invariants.duplicate_actions`: count reservations and bookings in the MOCKS beyond one per intended action.
2. `injector.fire` for `cancel_flight`, `change_carrier` and `drop_response` (plain HTTP calls to mock admin endpoints).
3. `kill_agent`: read the pid from `workers`, SIGKILL it, restart it after two seconds.
4. `invariants.ledger_matches_world` and `budget_respected`.
5. `random_run(seed)`: fire events at random moments, seeded so a failing run can be replayed.

## Done when

- Each named event can be fired from the command line and writes a chaos Event.
- A seeded random run prints the invariant results at the end.

## Do not

- Read our own ledger to decide if the run was correct. Ask the mock systems.

## Every reply ends with

1. What works now.
2. The exact command to run or test it.
3. What is still stubbed, and anything you need from another role.
