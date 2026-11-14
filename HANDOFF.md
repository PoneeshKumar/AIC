# ColdTrace handoff

For Dvij and Poneesh. Read this once before you start, then keep it open all day.

**Event:** Agents in Context Toronto, a MongoDB hackathon. Saturday Nov 14, The Quay.
**Hacking:** 10:45 AM to 5:00 PM. Round one judging 5:15 PM. Finals 7:00 PM.
**Track:** Statement Three, Finish the Job.

---

## 1. The idea in one paragraph

A shipment of temperature-sensitive medicine is in the air between Toronto and Vancouver when its connecting flight is cancelled. Every minute it spends outside cold storage uses up a fixed budget, and when the budget is gone the product is lost. ColdTrace is an agent that takes over the recovery: it re-solves the route, holds qualified cold storage, rebooks the carrier and updates the hospital. What makes it different is that it never trusts its own messages. A step only counts once the other system confirms it, so the agent can be killed mid-run, lose a response, or have the carrier change its API underneath it, and still finish the job without booking anything twice.

**The pitch line:** "Other agents retry what failed. Ours checks what really happened and re-plans from there."

## 2. Why this fits the track

| Track 3 asks | Our answer | Demo beat |
|---|---|---|
| How does it tell an action that took effect from one only sent? | Steps move `planned → sent → verified`, and verified requires a separate read of the target system | Step turns green only after the warehouse confirms |
| How does it resume after a crash without replaying history? | On restart it resolves every `sent` step by reading, then continues from the ledger | Kill the agent after it reserves storage |
| How does it adapt when a system's fields change? | Vector Search finds a similar past incident, the agent proposes a mapping, a human approves, it becomes a stored rule | Carrier API flips to a new format |

We also touch the other two statements, and should say so in one sentence only:

- **Audit:** every step records what was done, why, and who authorized it, so a reviewer can reconstruct the run.
- **Memory:** an approved fix changes behaviour on the next run, and a human correction supersedes a wrong memory.

## 3. Impact

**Who has the problem:** drug manufacturers, logistics providers, specialty distributors and hospital pharmacies. When a shipment goes wrong today, a coordinator spends hours on the phone with carriers and warehouses while the clock runs.

**How big it is, using only claims we can cite** (full table in `docs/PITCH_SOURCES.md`):

- In a systematic review of published studies, 14% to 35% of fridges or transport shipments exposed vaccines to freezing temperatures (Matthias et al., *Vaccine*, 2007).
- A later update covering 45 studies found the problem continuing in wealthy and lower income countries alike (Hanson et al., *Vaccine*, 2017).
- The industry estimate for the cost of failures in temperature-controlled logistics is about $35 billion a year (attributed to the IQVIA Institute, via trade press).

**Three lines we stay behind:**

1. Say "out of range", not "too hot". The best documented failure is freezing.
2. The agent quarantines and reroutes. It never says a product is safe to use. A qualified person decides that. (AI medical advice is an instant disqualification.)
3. Our shipment, product and systems are simulated, and we say so.

## 4. Where the data comes from

Everything functional runs on systems we build, so real data is for credibility and not for making it work.

| Data | Source | Where it lives |
|---|---|---|
| Pitch statistics | Peer-reviewed reviews and industry estimates in `docs/PITCH_SOURCES.md` | `docs/PITCH_SOURCES.md` |
| Shipment and product | Synthetic, in `data/seed/shipment.json`. Fictional product, invented budget. | Seed file |
| Routes | Real Canadian airport codes with invented flight times, in `data/seed/routes.json` | Seed file |
| Cold storage sites | Synthetic, in `data/seed/warehouses.json` | Seed file |
| Past incidents (the memory) | Hand-written synthetic incidents, write 15 to 20 | `data/seed/past_incidents.json` |
| Temperature trace | Simulated by the budget clock | Runtime only |

**Optional realism if there is time:** swap invented flight times for a public route dataset such as OpenFlights. This is a nice touch and not worth a minute before the 3:00 checkpoint.

**We do not use:** real product names in the demo, real storage limits for any product, or anyone's real shipment data.

## 5. How it works

```
                    ┌─────────────── Atlas (hackathon sandbox) ───────────────┐
                    │ shipments  runs  steps  events  memories  workers       │
                    └──────▲──────────────▲───────────────────▲───────────────┘
                           │              │                   │
   chaos buttons ──► server/ (UI backend) │            agent/ (the worker process)
        │                  ▲              │              │  plan → send → verify
        │                  │ polls        │              │  resume, adapt
        ▼                  │              │              ▼
   chaos/injector ─────────┴──────────────┴──► mocks/ carrier · warehouse · hospital
                                                (separate processes, own state, no Atlas)
```

### The verified ledger (CORE)

One document in `steps` per action. The rules:

1. Write `sent` before the request leaves, so a crash leaves a trace.
2. Write `verified` only after a separate read shows the effect, and store that response as evidence.
3. On restart, resolve every `sent` step by reading. Never resend blind.
4. Every write carries a stable idempotency key.

### How the re-solve works (PLANNER)

Each candidate route has legs. A leg or layover that is not cooled eats the excursion budget, unless a qualified cold storage bay is held for that layover. The planner drops routes that exceed the remaining budget, picks the one leaving the most budget, and returns the ordered steps plus a plain reason for each rejected route. It plans from verified state, so anything already confirmed is reused.

It is a pure function with no network calls and no LLM, which makes it exact, fast to test and easy to defend.

### Memory and drift (MEMORY)

When the carrier answers in a shape we don't understand, the agent summarizes the failure, runs `$vectorSearch` over past incidents (Voyage embeddings, filtered by system), and asks the model for a proposed mapping. The proposal waits for a human. Once approved it is stored as a rule and applied by ordinary code from then on. A second shipment hitting the same drift does not fail first, which is our proof that memory changed behaviour.

### Where the "agent" is

A judge will ask this. The model does three things: it turns a disruption into a recovery goal and explains each step, it diagnoses failures it has not seen before, and it proposes fixes from retrieved experience. The ledger is what makes it safe to let it.

### Demo screen (UI)

One page: budget clock, duplicate actions counter, steps verified, the plan with a status per step, four system cards, four chaos buttons and the event log. The plan and the log are the centre of attention. Plain HTML polling `/state` once a second.

## 6. Key decisions already made

| Decision | Choice | Why |
|---|---|---|
| Language | Python | Both of us know it |
| Agent loop | Our own loop over the `steps` ledger | The ledger already gives us resume. LangGraph adds unknowns at 11 AM. Use it only if Poneesh already knows it well. |
| Tracing | LangSmith, if it takes under 15 minutes | Free answer to "what did the agent do" |
| Embeddings | Voyage AI | 200M free tokens from the event |
| Planner | Enumerate and score | 3 to 6 routes, exact, no solver licence risk |
| UI | Plain HTML | No build step, no Streamlit (banned) |
| Mock state | In memory, per process | Keeps them separate from Atlas |

## 7. The workers

Each role is a Claude session with one job and its own directories, so sessions never edit the same file. Role files are in `workers/`.

**To start a worker:** open a new Claude Code session in this repo and say:

> You are the MOCKS worker. Read CLAUDE.md, HANDOFF.md and workers/coldtrace-mocks.md, then start on the first item.

| Label | Lane | Owns | Starts | Job |
|---|---|---|---|---|
| **CORE** | Poneesh | `core/`, `agent/run.py`, `ledger.py`, `verify.py` | 11:05 | Verified ledger, agent loop, resume |
| **PLANNER** | Poneesh | `agent/planner.py`, `scripts/seed.py` | 11:05 | Route and storage re-solve |
| **MOCKS** | Dvij | `mocks/`, seed data | 11:05 | The three fake systems, idempotency, fault switches |
| **CHAOS** | Dvij | `chaos/` | 11:45 | Fault injector and invariant checks |
| **UI** | Dvij | `server/`, `ui/` | 12:15 | The demo screen |
| **MEMORY** | Dvij | `agent/memory.py`, `adapt.py`, `past_incidents.json` | 12:15 | Vector Search memory and drift handling |
| **PM** | Akil | `README.md`, `docs/`, board, `tests/` sign-off | 10:45 | Checkpoints, scope cuts, QA, pitch, submission |

See `docs/TEAM.md` for the working rules.

**How to run them well:**

- **Two sessions per person at a time.** More than that and you stop reading what they produce.
- **You are the integrator.** Workers report at the end of each reply: what works, how to run it, what's stubbed. Run the command yourself before accepting it.
- **Contracts are the handshake.** `docs/CONTRACTS.md` and `core/models.py` are frozen. Any change goes through both of you, out loud.
- **One trunk.** Commit small, `git pull --rebase` before starting and before pushing. Owned directories keep conflicts rare.
- **QA never fixes.** It reports with exact steps, and the owning session fixes.

## 8. Timeline

### Before 10:45 (accounts and tools, no code)

| Who | What |
|---|---|
| Both | Find the Atlas Sandbox email and create the project and cluster through that link |
| Both | Check in at the venue, since partner credits unlock at check-in |
| Both | Create Voyage AI and LangSmith accounts and keys |
| Both | Install the MongoDB plugin for Claude Code (section 10) |
| Both | Read sections 1 to 6 together and agree the contracts out loud |

### Hack day

| Time | Dvij | Poneesh | Checkpoint |
|---|---|---|---|
| 10:45 | Kickoff together: create the public repo, lay down the skeleton and contracts, fill `.env`, `bash scripts/dev.sh check` passes on both laptops, first commit | | |
| 11:05 | Start MOCKS | Start CORE and PLANNER | |
| 11:45 | Start CHAOS (invariants first) | CORE happy path against mocks | |
| 12:15 | Start UI once `/state` shape is real | Resume logic | |
| **12:45** | | | **Happy path: cancel flight, every step verified** |
| 1:00 | Lunch at the desk, in turns | | |
| **1:45** | Kill button wired to UI | Kill and restart is clean | **MUST tier: crash and resume, duplicates = 0** |
| 1:45 | MOCKS adds carrier schema v2. Start QA. | Start MEMORY | |
| 2:20 | Proposal card with Approve | Proposal flow end to end | |
| **3:00** | | | **SHOULD tier: all three beats run back to back** |
| 3:00 | One stretch goal at most | Random chaos passing | |
| **3:30** | **Feature freeze.** Akil starts submission prep. | QA loop, demo-breaking fixes only | |
| 4:00 | Record the video | Repo public, no secrets, clean clone runs | |
| 4:15 | Video done, audio checked | | |
| 4:40 | Submit, add both names | | **Submitted** |
| 4:40 to 5:00 | Rehearse the three minutes twice | | |
| 5:15 | Round one | | |

### The cut rule

- **If the 1:45 checkpoint is missed:** drop random chaos and every stretch goal. Memory becomes a single hard-coded proposal flow. Protect the crash beat.
- **If the 3:00 checkpoint is missed:** demo two beats well. Do not start anything new.

### Stretch goals (pick one, only after 3:00)

1. **Second worker with a lease.** Two agents, a judge kills either one. About an hour.
2. **Correction beat.** A human edits the proposed fix and the next shipment gets it right first time.
3. **Voice approval with ElevenLabs.** Qualifies for their prize. Most likely to fail live, so keep the button as a fallback.

## 9. The demo beats

Full script with timings and likely questions is in `docs/DEMO_SCRIPT.md`.

1. **Cancel the flight.** The agent re-solves and steps turn green as systems confirm.
2. **Kill the agent.** It restarts, reads the warehouse, and reservations stay at one.
3. **Change the carrier API.** Memory hit, proposal, approval, stored rule.
4. **Random chaos.** A failure we did not choose.

On screen the whole time: budget remaining, and duplicate actions at 0.

## 10. Setup and tooling

| Tool | What it does | How |
|---|---|---|
| MongoDB plugin for Claude Code | Bundles MongoDB Agent Skills and the MongoDB MCP Server | `claude plugin install mongodb@claude-plugins-official` |
| MCP Server connection | Lets a session inspect collections and create indexes on our cluster | `npx mongodb-mcp-server@1 setup`, paste the sandbox connection string |
| Query prompting | How to ask a session for a good query | Checklist at the bottom of `docs/CONTRACTS.md` |

Nothing needs installing remotely. The only remote piece is the Atlas cluster, which you create through the sandbox link.

## 11. Submission checklist

- [ ] Project and cluster created through the Atlas Sandbox link (finalist requirement)
- [ ] Repo public, `.env` not committed, no keys in history
- [ ] README run steps work on a clean clone
- [ ] One minute video with working audio, showing code and functionality
- [ ] Short project description
- [ ] Both team members added on the Cerebral Valley submission
- [ ] Demo shows only what was built during the event
- [ ] Submitted by 4:40, not 4:59

## 12. If you remember nothing else

**Three systems, three beats, one clock.**
**Clock, count, kill, change.**
**Prove it in the room, sell it on the stage.**
