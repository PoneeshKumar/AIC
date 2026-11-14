# ColdTrace: rules for every Claude session in this repo

ColdTrace is our entry for the MongoDB "Agents in Context" hackathon (Track 3, Finish the Job). An agent rescues a temperature-sensitive shipment when its flight is cancelled, and it must survive crashes, lost responses and a carrier API change without doing anything twice.

## Read first

1. `HANDOFF.md` for the idea, the plan and your role.
2. `docs/CONTRACTS.md` for the shapes you build against.
3. Your role file in `workers/`.

## Rules

- **Stay in your lane.** Each role owns specific directories (see your role file). Do not edit files another role owns. If you need a change there, write the request in your reply so a human can route it.
- **Contracts are frozen.** Do not change `core/models.py` or `docs/CONTRACTS.md` without a human saying yes.
- **Verified means read back.** Never mark a step verified from a write response.
- **Mocks never touch Atlas.** They are other people's systems.
- **No secrets in the repo.** Keys live in `.env`, which is gitignored. The repo goes public at submission.
- **Atlas sandbox only.** The cluster must be the one created through the hackathon sandbox link.
- **Small commits, pull often.** `git pull --rebase` before you start and before you push.
- **Report like a teammate.** End every reply with: what works now, how to run it, what is still stubbed.

## Things that would disqualify us

- No Streamlit, and the dashboard must not be the main feature. The agent's recovery is the product.
- The agent never gives medical advice and never declares a product safe or unsafe. It quarantines and reroutes.
- Only show work built during the event in the demo.

## Writing style for any prose (docs, README, pitch, UI copy)

- No em dashes and no semicolons. Write sentences that flow in one breath.
- Sentence case, short and concrete.

## Stack

Python 3, FastAPI for mocks and the UI backend, pymongo, Atlas Vector Search, Voyage AI embeddings, plain HTML for the screen. Run things with `bash scripts/dev.sh <command>`.

## MongoDB tooling

The MongoDB plugin for Claude Code (Agent Skills plus the MongoDB MCP Server) should be installed. Use the MCP server to inspect collections and create indexes. When writing a query, follow the checklist at the bottom of `docs/CONTRACTS.md`.
