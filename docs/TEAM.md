# Team

| Person | Role | Owns |
|---|---|---|
| Poneesh | Dev A, agent brain | `core/`, `agent/run.py`, `agent/ledger.py`, `agent/verify.py`, `agent/planner.py`, `scripts/seed.py` |
| Dvij | Dev B, world and surface | `mocks/`, `chaos/`, `server/`, `ui/`, `data/seed/` (shipment, routes, warehouses, past incidents), `agent/memory.py`, `agent/adapt.py` |
| Akil | PM | `README.md`, `HANDOFF.md`, `docs/`, board, `tests/` sign-off, demo, submission |

## Working rules

1. **Contracts are frozen.** `core/models.py` and `docs/CONTRACTS.md` change only by PR with both devs approving. Akil announces the change.
2. **One lane per PR.** Touch only your owned paths. For another lane, tag its owner.
3. **One writer per shared file.** `scripts/seed.py` is Poneesh's, and Dvij supplies data as JSON. The vector index in `core/db.py` comes from Dvij as a small PR, and Poneesh merges it within 10 minutes.
4. **Branches.** Keep `main` green. Use `<name>/<topic>` branches, squash merge, rebase first, and keep PRs under about 150 lines.
5. **Done means:** it runs through `scripts/dev.sh`, `pytest tests/test_scaffold.py` passes, and the PR says what works, how to run it, and what is stubbed.
6. **Keep stub signatures stable** so the other lane can build against them from the start.
7. **Lanes meet only at:** HTTP to the mock servers, `/admin/*`, Atlas collections, and the `/state` JSON.

## Cadence (Akil runs it)

- 10:45 kickoff: confirm lanes and the board (Next, Doing, Review, Done).
- Blocker check-ins at 11:30, 12:30 and 2:15.
- Checkpoints: 12:45 happy path, 1:45 crash and resume, 3:00 all demo beats, 3:30 feature freeze.
- At each checkpoint Akil decides what is cut. Stretch goals go first.
- 3:30 to 4:30: two demo rehearsals, backup video, submission checklist. Submit by 4:40.

## Timeline

| Time | Poneesh | Dvij | Akil |
|---|---|---|---|
| 10:45-11:05 | models and db check, ledger skeleton | carrier, warehouse, hospital with idempotency | board, contracts review, demo script |
| 11:05-12:15 | ledger, verify, run loop | fault injection, chaos injector, `/state`, UI | pitch sources, review 15 to 20 seed incidents |
| 12:15-12:45 | planner, happy path wired | memory `embed`, `recall`, vector index | test happy path, file bugs |
| 12:45-1:45 | resume after crash | `adapt` propose and apply, approval UI | un-skip invariant tests |
| 1:45-3:00 | adapt integration, chaos runs | chaos polish, UI states | QA runs, rehearsal 1 |
| 3:00-3:30 | bug fixes | bug fixes | freeze go or no-go |
| 3:30-4:40 | fixes only | fixes only | rehearsal 2, backup video, submit |
