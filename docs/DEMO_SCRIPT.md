# Demo script

Three minutes live, then one to two minutes of questions. Rehearse it at least three times after the 3:30 freeze.

## Setup before you walk up

- Mocks, server and agent running. Screen on the demo page, terminal visible beside it.
- Run `POST /admin/reset` on each mock and reseed, so counters start clean.
- An Atlas tab open on the `steps` collection for questions.

## The script

| Time | Do | Say |
|---|---|---|
| 0:00 | Screen at rest, clock ticking | "This medicine can only spend so long outside its temperature range. That clock is how long we have." |
| 0:20 | Press Cancel flight | "The flight is gone. Watch it re-solve the route and hold cold storage. A step only turns green when the other system confirms it." |
| 1:00 | Press Kill agent, then restart | "It died after reserving storage. On restart it asks the warehouse what exists before acting. Reservations, still one." |
| 1:45 | Press Change carrier API | "The carrier changed its format. It finds a similar past incident, proposes a fix, I approve, and that is now a stored rule." |
| 2:30 | Press Random chaos | "We picked those failures. We did not pick this one." |
| 2:50 | Point at the counters | "Delivered inside the budget, zero duplicates, every step on record in Atlas." |

## Round one vs round two

- Round one (small room, 65% engineering): open with the crash. Keep the terminal visible.
- Round two (stage, if we make top six): open with the pain in one sentence, then the same beats.

## Likely questions

| Question | Answer |
|---|---|
| Where is the agent, isn't this a workflow engine? | The model plans the recovery, diagnoses failures it has not seen, and proposes fixes. The ledger is what makes it safe to let it. |
| Why not just retry? | A retry after a lost response books twice. We read first, so we know. |
| Why MongoDB? | Our records are evidence from systems we don't control and their shapes change. One document per step stores what each system said and updates atomically. Memory and state sit in one place, so one query filters and searches by meaning. |
| Is the agent deciding the medicine is safe? | No. It quarantines and reroutes. A qualified person decides disposition. |
| Is this real data? | The systems and shipment are simulated. The problem size comes from published studies, listed in our README. |
| What would you build next? | Multiple workers with leases, and per-customer memory isolation. |

## One minute video (record by 4:15)

Same three beats at double speed, screen recording with voice over. Check that audio plays back before uploading. Show a few seconds of code.
