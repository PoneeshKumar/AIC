# ColdTrace next handoff

Updated: 2026-11-14
Branch: `pk-implementation`

This is the current implementation status for the next Poneesh session. Keep `docs/poneesh/PLAN.md` as the original implementation plan.

## Completed

- `agent/planner.py`
  - Scores routes by remaining excursion budget.
  - Rejects routes over budget with a reason.
  - Breaks ties deterministically by arrival and route ID.
  - Reuses only a verified booking for the selected route.
  - Reuses only a verified reservation for the selected warehouse.
  - Emits quarantine, storage, booking, and hospital steps.
  - Emits a quarantine step when no route is feasible.
  - Requires `run_id` and `shipment_id` instead of silently inventing defaults.
- `agent/ledger.py`
  - Idempotent plan insertion.
  - Reopens skipped or failed steps when a matching plan is replayed.
  - Atomic leased step claims.
  - Forward-only status transitions.
  - Prevents later steps from running while an earlier step is sent or failed.
  - Supports unresolved sent-step lookup for resume.
- `agent/verify.py`
  - Performs target-system read-back checks.
  - Matches reservations and bookings by idempotency key.
  - Verifies hospital status and ETA.
  - Returns a false result for target-system 404 responses.
- `agent/memory.py`
  - Stores missing embeddings through Voyage.
  - Uses document embeddings for storage and query embeddings for recall.
  - Uses Atlas Vector Search with an active-memory filter.
  - Removes embeddings and stringifies IDs before returning matches.
  - Stores corrections before superseding the original memory.
- `agent/adapt.py`
  - Creates one pending proposal per identical failure.
  - Uses the closest Atlas memory as the human-review proposal.
  - Applies approved mappings deterministically.
  - Raises on missing paths and unknown transforms.
- `agent/run.py`
   - Registers and heartbeats the worker.
   - Loads or creates a recovery run.
   - Resolves sent steps before planning.
   - Converts carrier routes and warehouse capacity into planner inputs.
   - Sends idempotent HTTP writes and verifies each one by read-back.
   - Persists plan, send, verify, resume, and finish events.
- `core/db.py` and `core/models.py`
  - Atlas connection and standard indexes exist.
  - Worker and step idempotency indexes exist.
  - Memories have an explicit `active` flag.
- `tests/test_planner.py`
  - Covers route choice, verified reuse, route mismatch, no feasible route, and determinism.
- Configuration no longer requires an LLM or Anthropic key.

## Validation completed

- Python compilation passes with:

  ```bash
  python3 -m compileall -q agent core tests
  ```

- Editor diagnostics report no errors.
- `git diff --check` passes.
- Direct planner regression assertions pass.

## Validation still blocked

- `pytest` cannot run in the current interpreter because the package is not installed.
- Atlas connectivity and the Atlas Vector Search index have not been tested here.
- Voyage-backed memory behavior has not been tested against a live Atlas cluster.
- The mock services are still stubs, so end-to-end verification is not possible yet.

## Still incomplete

### Highest priority

1. `mocks/common.py`
   - Implement idempotency storage.
   - Apply fail-before-write and drop-after-write faults.
   - Preserve idempotency keys in stored records.
2. `mocks/carrier.py`
   - Implement shipment and route reads.
   - Implement idempotent bookings and booking reads.
   - Implement flight cancellation and schema switching.
3. `mocks/warehouse.py`
   - Implement capacity reads.
   - Implement idempotent reservations and reservation reads.
4. `mocks/hospital.py`
   - Implement idempotent delivery updates and delivery reads.
6. `agent/run.py` drift integration
   - Connect unknown carrier response handling to `adapt.propose_fix`.
   - Stop for human approval before applying a new rule.
7. `scripts/seed.py`
   - Upsert shipment, routes, warehouses, and memories.
   - Batch incident embeddings through Voyage.
7. `core/db.py`
   - Add and document the Atlas Vector Search index definition for `memories.embedding`.

### After the happy path

8. `chaos/injector.py`
   - Implement cancellation, agent kill, carrier schema change, dropped responses, and seeded random runs.
9. `chaos/invariants.py`
   - Count duplicate actions from the mock systems.
   - Compare verified ledger steps with the external systems.
   - Check the excursion budget.
10. `server/app.py` and `ui/index.html`
    - Implement `/state`, `/chaos/{event}`, and `/approve`.
    - Render steps, events, counters, systems, and pending proposals.
11. Tests
    - Add `tests/test_ledger.py` for idempotent writes, ordering, leases, and crash recovery.
    - Unskip and implement `tests/test_invariants.py` acceptance cases.

## Required execution order

1. Complete the three mock systems and shared fault/idempotency behavior.
2. Run `agent/run.py` against the real mock HTTP contracts.
3. Complete seeding and create the Atlas Vector Search index.
4. Run the happy path until every step is verified.
5. Add crash/resume and dropped-response checks.
6. Add chaos and invariants.
7. Implement the UI state, chaos controls, and approval flow.
8. Run the full test suite and all demo beats.
9. Update the main README and demo documents with commands that actually work.

## Acceptance commands

```bash
bash scripts/dev.sh check
bash scripts/dev.sh test
bash scripts/dev.sh mocks
bash scripts/dev.sh seed
bash scripts/dev.sh agent --shipment BIO-2048
bash scripts/dev.sh server
```

Acceptance requires:

- Cancelled flights produce a valid re-plan.
- Every completed action is verified by a read-back.
- Killing the agent after a sent write does not create a duplicate reservation or booking.
- Dropped responses are resolved by reading the target system, never by blind retry.
- Carrier schema drift creates one pending proposal and approval stores a reusable rule.
- Duplicate actions remain zero.
- No medical safety decision is made by the agent.

## Lane rules

- Keep `core/models.py` and `docs/CONTRACTS.md` frozen unless both humans approve a change.
- Mocks never read or write Atlas.
- Keep MEMORY-owned changes coordinated with the MEMORY worker.
- Keep UI and chaos changes in their owned lanes.
- Do not commit secrets. `.env` remains local and ignored.
- End each worker update with what works, how to run it, and what remains stubbed.

## Current decision

The no-LLM adaptation path is intentional. Atlas Vector Search retrieves similar incidents, the closest stored fix becomes a proposal, and a human approves it. Adding an LLM-generated proposal requires an explicit team decision and is not part of the current implementation.
