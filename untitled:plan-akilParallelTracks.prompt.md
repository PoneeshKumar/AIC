## Plan: Akil Branch Tour and Parallel Tracks

Akil will first inspect everyone’s work safely, then create two separate branches: one for acceptance tests and one for UI polish. This keeps QA and design changes isolated from your core implementation and Dvij’s mock/server work.

**Phase 1: Branch tour**

1. Use a separate worktree so Akil does not disturb uncommitted changes.
2. Inspect `main` as the original scaffold.
3. Inspect `pk-implementation` for your planner, ledger, verifier, memory, seed, and runner work.
4. Inspect Dvij’s branch once its name is available, focusing on `mocks/`, `chaos/`, `server/`, and `ui/`.
5. Create a written comparison:
   - What each branch contains
   - What remains incomplete
   - Which contracts connect the branches
   - Which files would conflict during integration

Current known local branches are `main` and `pk-implementation`. Dvij’s branch needs to be identified before Akil can inspect it.

**Phase 2: Tests branch**

Create:

```bash
git switch -c akil/acceptance-tests
```

Akil should own only:

- `tests/`
- Test configuration if needed

He should enable and implement:

- Happy path
- Kill and resume
- Dropped response
- Carrier schema change
- Second run using stored memory
- Seeded random chaos

He should not modify production code, `core/models.py`, or `docs/CONTRACTS.md` to make tests pass.

Verification:

```bash
pytest -q tests/test_scaffold.py tests/test_ledger.py tests/test_planner.py tests/test_invariants.py
git diff --check
```

**Phase 3: UI polish branch**

Create this only after Dvij’s server and UI integration is available:

```bash
git switch -c akil/ui-polish
```

Before editing, Akil should search for the requested skill:

```bash
npx skills find frontend ui engineering
```

If the exact `/frontend-ui-engineering` skill is found from a trusted source, install the package returned by the search:

```bash
npx skills add <owner/repo@skill> -g -y
```

If it is not found, Akil should record that and use the repository’s existing plain HTML/CSS/JavaScript approach.

The UI should be optimized for nontechnical users:

- Large remaining budget display
- Duplicate actions prominently showing `0`
- Verified step progress such as `3 of 6`
- Plain-language recovery steps
- Clear system health indicators
- Readable chronological event log
- Obvious chaos controls
- Loading, error, and stale-data states
- Proposal approval card
- No medical claims that a shipment is safe or unsafe

The UI branch must not silently change the `/state` contract. Any missing backend field goes to Dvij for coordination.

**Branch ownership**

- You: `agent/`, `core/`, planner, ledger, verifier, runner, and seed integration
- Dvij: `mocks/`, `chaos/`, `server/`, `ui/`, and any explicitly agreed memory/data work
- Akil tests branch: `tests/` only
- Akil UI branch: `ui/` only, unless Dvij explicitly coordinates server changes

**Final gates**

Before integration:

```bash
bash scripts/dev.sh check
bash scripts/dev.sh test
git diff --check
```

Then validate:

- Cancelled-flight recovery
- Crash and resume
- Dropped response recovery
- Carrier schema approval
- Zero duplicate actions
- UI updates within one second
- Clean clone setup
- No secrets committed

The plan is saved in session memory for Akil’s handoff.