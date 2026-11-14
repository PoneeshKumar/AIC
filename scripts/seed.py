"""Loads data/seed/*.json into Atlas. Owner: MEMORY (incidents) and MOCKS (shipment).

TODO(MEMORY): embed each past incident with Voyage and insert into `memories`.
TODO(MOCKS): insert the demo shipment into `shipments`.
"""
import json
from pathlib import Path

SEED_DIR = Path(__file__).resolve().parent.parent / "data" / "seed"


def load(name):
    return json.loads((SEED_DIR / name).read_text())


if __name__ == "__main__":
    raise SystemExit("seed.py is a stub. See the TODOs at the top of this file.")
