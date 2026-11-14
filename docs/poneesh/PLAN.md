# Poneesh implementation plan

Covers the CORE, PLANNER and MEMORY lanes from `HANDOFF.md`. Each stage is built by one agent session and checked with the ponytail skill and a real Atlas run before the next stage starts.

## Context

The scaffold exists as stubs in `agent/` (`ledger`, `verify`, `run`, `planner`, `memory`, `adapt`), `core/` (`db`, `config`, `models`) and `scripts/seed.py`. The contracts in `core/models.py` and `docs/CONTRACTS.md` are frozen. The goal is working code with clean structure, real Atlas integration and docs that make the demo easy to run and explain.

Lane rules still hold. Agents do not edit `mocks/`, `server/`, `ui/`, `chaos/`, `README.md` or anything else in `docs/` outside `docs/poneesh/`. Needs from other roles are listed at the end.

## Agent sessions

Run at most two at a time, as HANDOFF advises.

| Agent | Owns | Starts |
|---|---|---|
| PLANNER | `agent/planner.py`, `tests/test_planner.py`, shipment, routes and warehouse parts of `scripts/seed.py` | Now, it is pure and has no dependencies |
| CORE | `core/db.py`, `agent/ledger.py`, `agent/verify.py`, `agent/run.py` | Now, ledger first |
| MEMORY | `agent/memory.py`, `agent/adapt.py`, incident embedding in `scripts/seed.py` | After the CORE happy path |
| DOCS | `agent/README.md`, `core/README.md`, `scripts/demo_trace.py` | After each stage lands |

Start every prompt with: "You are the X worker. Read CLAUDE.md, HANDOFF.md and workers/coldtrace-x.md. Use the ponytail skill and keep it on."

## Stage 1: PLANNER

- `solve(budget_minutes, routes, verified_state) -> Plan` in `agent/planner.py`, keeping the existing `RouteOption` and `Plan` dataclasses.
- Uncooled minutes are the uncooled legs plus any layover with no reserved bay. Drop routes over budget, pick the most budget left, break ties on earliest arrival.
- Plan from verified state. A reservation or booking that already exists and still fits is reused and not created again.
- `rejected` holds a plain reason per route, for example "needs 140 uncooled min, 90 left". When no route fits, return a clear no-feasible-route result and do not raise.
- Emit ordered steps (`set_quarantine`, `reserve_storage`, `rebook_carrier`, `notify_hospital`) with a `reason` and the key `"{run_id}:{action}:{target}"`.
- Tests in `tests/test_planner.py` cover a cancelled direct flight, a layover with no free bay, a budget too small for any route, a re-solve after a partial run, and same input giving same output.
- Finish the shipment, routes and warehouses seeding in `scripts/seed.py` as an idempotent upsert.

## Stage 2: CORE

1. `core/db.py`: keep `get_db` and `ensure_indexes`. Add a unique index on `workers.worker_id`. The unique index on `steps.idempotency_key` is the main Atlas talking point.
2. `agent/ledger.py` on pymongo:
   - `write_plan` inserts each step and ignores `DuplicateKeyError`, so replays are safe.
   - `next_step` uses `find_one_and_update` on `status: planned`, sorted by `seq`, and sets the lease.
   - `mark_sent`, `mark_verified` and `mark_failed` use `update_one` with the expected old status in the filter, so status only moves forward. A filter miss raises.
   - `unresolved_sent_steps` queries `status: sent`.
3. `agent/verify.py`: one read-back per action over `httpx` against the URLs in `core/config.py`. For `reserve_storage` it reads `GET /reservations` and matches our idempotency key. It returns `(took_effect, evidence)` and never looks at a write response.
4. `agent/run.py` follows its docstring: register and heartbeat, load or create the run, resume every `sent` step by reading, plan if needed, claim, mark sent, send with `Idempotency-Key`, verify, and write one `Event` per decision. Carrier drift calls `adapt`, which stays a stub until Stage 3.
5. The duplicate counter is never computed by the agent. It comes from the warehouse `GET /reservations`.

Tests: `tests/test_ledger.py` runs against a separate `coldtrace_test` database on the sandbox cluster and drops it afterward. A crash test stops after `mark_sent`, restarts, and asserts one reservation and a finished run.

## Stage 3: MEMORY

- `memory.py` gets `embed` (Voyage), `remember`, `recall` (`$vectorSearch` filtered on `system`, skipping superseded memories) and `correct`.
- Create the vector index on `memories.embedding` with filter fields `system` and `kind` through the MongoDB MCP server. Save its definition in `core/db.py` so a clean clone can recreate it.
- `adapt.py` gets `propose_fix` (recall, ask the LLM, write a `proposals` document, stop) and `apply_rule` (a plain dict mapping with no LLM).
- `scripts/seed.py` embeds the 15 to 20 incidents in `past_incidents.json` in one batched Voyage call and upserts them.

## Ponytail gate

Run at the end of every stage.

1. The agent runs `/ponytail-review` on its own diff and fixes what it finds.
2. The integrator runs `/ponytail-review` again, then `/ponytail-debt` to list every `shortcut:` comment and decide whether to keep it.
3. Run `/ponytail-audit` once at the 3:30 freeze across the whole repo.
4. Reject any abstraction layer, unused option or code that nothing calls.

## Atlas checks

Use the sandbox cluster only.

- `bash scripts/dev.sh check` passes and `ensure_indexes()` runs cleanly twice.
- The MongoDB MCP server confirms the indexes exist and shows `steps` after a run.
- Queries follow the checklist at the bottom of `docs/CONTRACTS.md`.
- `.env` is gitignored and no connection string appears in any file or test output.

## Demo docs

- `agent/README.md` shows the step lifecycle, what each file does, how to run it, and what to point at in Atlas (`steps`, `status`, `evidence`, `verified_by`).
- `core/README.md` lists the collections, the indexes, and the three Atlas talking points: unique key, atomic claim, and vector search with a filter.
- `scripts/demo_trace.py` prints a run's steps and events as a timeline from Atlas. It answers "how do you reconstruct a run" from a terminal.
- Every public function gets a one-line docstring naming the demo beat it serves.
- All prose follows the repo style: no em dashes, no semicolons.

## Requests for other roles

- Dvij (MOCKS): `GET /reservations` must return the idempotency key stored on each reservation, or verify cannot match it.
- Dvij (UI): `/state` should read `steps` and `events` from Atlas with the shapes unchanged.
- Akil (PM): link `agent/README.md` and `scripts/demo_trace.py` from `docs/DEMO_SCRIPT.md`.

## Verification

1. `bash scripts/dev.sh test` passes. The planner tests need no network.
2. Run `bash scripts/dev.sh mocks`, then `bash scripts/dev.sh seed`, then `bash scripts/dev.sh agent --shipment BIO-2048`. Every step ends `verified`.
3. Kill the agent after `reserve_storage` is `sent` and restart it. The warehouse shows one reservation and the run completes.
4. `python scripts/demo_trace.py` prints the full timeline.
5. Flip the carrier to schema v2. Memory returns a hit with a score, the proposal waits, approval stores a rule, and a second shipment passes first time.

## Every agent reply ends with

What works now, how to run it, and what is still stubbed.
