import mongomock

from agent import ledger
from core import config
from core.models import Step


def make_step(run_id: str, seq: int) -> Step:
    return Step(
        run_id=run_id,
        seq=seq,
        action=f"action-{seq}",
        system="warehouse",
        idempotency_key=f"{run_id}:action-{seq}",
    )


def test_write_plan_is_idempotent(monkeypatch):
    db = mongomock.MongoClient().coldtrace_test
    db[config.STEPS].create_index("idempotency_key", unique=True)
    monkeypatch.setattr(ledger, "get_db", lambda: db)
    step = make_step("run-1", 1)

    ledger.write_plan("run-1", [step])
    ledger.write_plan("run-1", [step])

    assert db[config.STEPS].count_documents({}) == 1


def test_next_step_does_not_skip_a_leased_earlier_step(monkeypatch):
    db = mongomock.MongoClient().coldtrace_test
    db[config.STEPS].create_index("idempotency_key", unique=True)
    monkeypatch.setattr(ledger, "get_db", lambda: db)
    first, second = make_step("run-1", 1), make_step("run-1", 2)
    ledger.write_plan("run-1", [first, second])

    claimed = ledger.next_step("run-1", "worker-a")
    assert claimed is not None and claimed.seq == 1
    assert ledger.next_step("run-1", "worker-b") is None