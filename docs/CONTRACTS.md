# ColdTrace contracts

These are the agreements between workers. If you need to change one, stop and tell Dvij and Poneesh first, because another session is building against it.

## Atlas collections (database: `coldtrace`)

| Collection | One document is | Written by |
|---|---|---|
| `shipments` | A shipment and its remaining excursion budget | MOCKS seed, CORE |
| `runs` | One recovery attempt for a shipment | CORE |
| `steps` | One action against one system (the verified ledger) | CORE |
| `events` | One line of the UI log | everyone |
| `memories` | A past fix or an approved rule, with an embedding | MEMORY |
| `workers` | A running agent process (worker id, pid, heartbeat) | CORE |
| `proposals` | A fix waiting for human approval | MEMORY, UI |

Field-level shapes live in `core/models.py`.

### Step lifecycle

```
planned -> sent -> verified
                -> failed
planned -> skipped        (after a re-plan)
```

1. `sent` is written BEFORE the request leaves, so a crash mid-request leaves a trace.
2. `verified` is written only after a separate read of the target system shows the effect.
3. On restart, every `sent` step is resolved by reading, never by resending.
4. `idempotency_key` is `"{run_id}:{action}:{target}"` and never changes across retries.

## Mock systems

All mocks share: `GET /health`, `GET|POST /admin/faults`, `POST /admin/reset`.
Writes take an `Idempotency-Key` header. The same key returns the original result and creates nothing.

### Carrier (port 8101)

| Call | Purpose |
|---|---|
| `GET /shipments/{id}` | Status and ETA. Shape depends on schema version (below). |
| `GET /routes?origin=&dest=` | Routes available right now (cancelled flights removed) |
| `POST /bookings` | Book a shipment onto a route. Body: `{shipment_id, route_id}` |
| `GET /bookings?shipment_id=` | The verifying read for a booking |
| `POST /admin/cancel_flight` | Chaos: `{flight}` |
| `POST /admin/schema` | Chaos: `{version: 1 or 2}` |

Schema v1:
```json
{"shipment_status": "delayed", "eta": "2026-11-14T18:00:00Z"}
```
Schema v2:
```json
{"tracking": {"state": "DISRUPTED", "estimated_arrival_epoch": 1794688800}}
```

### Warehouse (port 8102)

| Call | Purpose |
|---|---|
| `GET /capacity?city=` | Qualified bays free in a city |
| `POST /reservations` | Hold a bay. Body: `{shipment_id, warehouse_id, from, to}` |
| `GET /reservations?shipment_id=` | The verifying read, and the source for the duplicate counter |

### Hospital (port 8103)

| Call | Purpose |
|---|---|
| `PUT /deliveries/{shipment_id}` | Set the expected arrival. Body: `{eta, status}` |
| `GET /deliveries/{shipment_id}` | The verifying read |

## UI state (`GET /state` on port 8100)

```json
{
  "shipment": {"shipment_id": "BIO-2048", "status": "recovering", "budget_remaining_min": 222},
  "counters": {"duplicate_actions": 0, "steps_verified": 3, "steps_total": 6},
  "steps": [{"seq": 1, "action": "set_quarantine", "system": "hospital", "status": "verified", "reason": "..."}],
  "systems": {"carrier": {"ok": true, "schema_version": 2}, "warehouse": {"ok": true, "reservations": 1},
              "hospital": {"ok": true}, "agent": {"worker": "worker-1", "alive": true}},
  "proposal": null,
  "log": [{"ts": "14:02:11", "message": "resume: last verified step = reserve_storage"}]
}
```

## Asking an assistant for MongoDB queries

From MongoDB's natural language query guidance. Give the assistant all of these, every time:

1. Database name and what it holds.
2. Today's date, stated explicitly.
3. The annotated schema of each collection involved (paste from `core/models.py`).
4. Two or three real sample documents, with the embedding array trimmed.
5. The indexes that exist.
6. The question, and the output you want (a pymongo call, not prose).
