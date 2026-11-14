"""Load synthetic demo data into Atlas."""
import json
from pathlib import Path

from agent.memory import embed_many
from core import config
from core.db import ensure_indexes, get_db
from core.models import Memory


SEED_DIR = Path(__file__).resolve().parent.parent / "data" / "seed"


def load(name):
    return json.loads((SEED_DIR / name).read_text())


def seed_shipment(db) -> None:
    """Upsert the synthetic shipment used by the demo."""
    shipment = load("shipment.json")
    db[config.SHIPMENTS].update_one(
        {"shipment_id": shipment["shipment_id"]},
        {"$set": shipment},
        upsert=True,
    )


def seed_memories(db) -> None:
    """Embed and upsert synthetic incident memories."""
    incidents = load("past_incidents.json")["incidents"]
    embeddings = embed_many([incident["summary"] for incident in incidents])
    collection = db[config.MEMORIES]
    for incident, embedding in zip(incidents, embeddings):
        memory = Memory(
            kind=incident["kind"],
            system=incident["system"],
            summary=incident["summary"],
            fix=incident["fix"],
            active=True,
            embedding=embedding,
        )
        document = memory.model_dump()
        collection.update_one(
            {"system": memory.system, "summary": memory.summary},
            {"$set": document},
            upsert=True,
        )


if __name__ == "__main__":
    database = get_db()
    ensure_indexes()
    seed_shipment(database)
    seed_memories(database)
