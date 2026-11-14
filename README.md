# ColdTrace

An agent that rescues temperature-sensitive shipments when the supply chain breaks, and can prove what it actually did.

Built for Agents in Context Toronto, a MongoDB hackathon. Track 3: Finish the Job.

## Run it

```bash
bash scripts/setup.sh          # once per laptop
bash scripts/dev.sh check      # verify keys and Atlas
bash scripts/dev.sh mocks      # carrier, warehouse, hospital
bash scripts/dev.sh server     # demo screen on http://localhost:8100
bash scripts/dev.sh agent --shipment BIO-2048
```

## Read next

- `docs/TEAM.md`: who owns what and how we work together
- `HANDOFF.md`: the idea, the plan, the timeline and the worker roles
- `docs/CONTRACTS.md`: data shapes and mock APIs
- `docs/DEMO_SCRIPT.md`: the three minute demo
- `docs/PITCH_SOURCES.md`: the research behind the pitch

All shipments, products and systems here are simulated.
