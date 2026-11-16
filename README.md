# ColdTrace

An agent that rescues temperature-sensitive medicine shipments when the supply chain breaks, and can prove what it actually did (built for Agents in Context Toronto, a MongoDB hackathon).

<img width="1470" height="800" alt="coldtrace-SS" src="https://github.com/user-attachments/assets/b197b018-bb3f-4a01-8e63-424067ec3fd5" />

## Run it

```bash
bash scripts/setup.sh          # once per laptop
bash scripts/dev.sh check      # verify keys and Atlas
bash scripts/dev.sh mocks      # carrier, warehouse, hospital
bash scripts/dev.sh server     # demo screen on http://localhost:8100
bash scripts/dev.sh agent --shipment BIO-2048
```

## Read First

- `docs/TEAM.md`: who owns what and how we work together
- `HANDOFF.md`: the idea, the plan, the timeline and the worker roles
- `docs/CONTRACTS.md`: data shapes and mock APIs
- `docs/DEMO_SCRIPT.md`: the three minute demo
- `docs/PITCH_SOURCES.md`: the research behind the pitch

All shipments, products and systems here are simulated.
