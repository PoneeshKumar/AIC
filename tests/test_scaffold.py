"""Runs today. Confirms the scaffold wiring is intact."""
from fastapi.testclient import TestClient


def test_mocks_boot_and_faults_toggle():
    from mocks import carrier, hospital, warehouse

    for module in (carrier, warehouse, hospital):
        client = TestClient(module.app)
        assert client.get("/health").json()["ok"] is True
        assert client.post("/admin/faults", json={"drop_next_responses": 1}).json()["drop_next_responses"] == 1
        assert client.post("/admin/reset").json()["reset"] is True


def test_models_import():
    from core.models import Step, StepStatus

    step = Step(run_id="r1", seq=1, action="reserve_storage", system="warehouse", idempotency_key="r1:reserve_storage")
    assert step.status == StepStatus.PLANNED


def test_server_serves_ui():
    from server.app import app

    assert "ColdTrace" in TestClient(app).get("/").text
