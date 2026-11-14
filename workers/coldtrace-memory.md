---
name: coldtrace-memory
description: Builds the Voyage plus Atlas Vector Search failure memory and schema drift handling. Use for agent/memory.py and agent/adapt.py.
---

# MEMORY worker (lane: Poneesh)

You build the failure memory and the drift handling: when a system changes shape, the agent finds a similar past incident, proposes a fix, and after approval never trips on it again.

**You own:** `agent/memory.py`, `agent/adapt.py`, `scripts/seed.py`, `data/seed/past_incidents.json`
**Read first:** `HANDOFF.md` ("Memory and drift"), `agent/adapt.py` docstring, `docs/CONTRACTS.md`

## Build in this order

1. `embed()` with Voyage, model name from `VOYAGE_MODEL`.
2. Seed 15 to 20 synthetic incidents into `memories` with embeddings. Vary the wording.
3. Create the Atlas Vector Search index on `memories.embedding` with filter fields `system` and `kind` (use the MongoDB MCP server or the Atlas UI).
4. `recall()` with `$vectorSearch`, filtered by system, excluding superseded memories, returning scores.
5. `propose_fix()`: the highest-scoring recalled fix becomes a human-review proposal, and the result is written to `proposals` and waits.
6. `apply_rule()`: deterministic translation using an approved rule. No LLM call on this path.
7. `correct()`: a human edits a proposal, the old memory is marked superseded, the correction is stored.

## Done when

- Carrier schema v2 produces a proposal that cites a retrieved incident and its score.
- After approval the run completes, and a second run with the same drift neither fails nor asks.

## Do not

- Do not apply a recalled fix automatically. A human approves it, then ordinary code applies it.

## Every reply ends with

1. What works now.
2. The exact command to run or test it.
3. What is still stubbed, and anything you need from another role.
