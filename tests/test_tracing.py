import time

from agent import tracing
from core import config


def test_tracing_is_pass_through_when_off(monkeypatch):
    monkeypatch.setattr(config, "LANGSMITH_TRACING", False)

    @tracing.traced("test")
    def identity(value):
        return value

    assert identity("value") == "value"


def test_trace_inputs_drop_database_records():
    assert tracing._safe_inputs({
        "db": object(),
        "run": {"secret": "hidden"},
        "shipment": {"shipment_id": "BIO-2048"},
        "run_id": "run-1",
        "count": 2,
    }) == {"run_id": "run-1", "count": 2}


def test_trace_url_uses_one_async_lookup(monkeypatch):
    class FakeClient:
        reads = 0
        urls = 0

        def read_run(self, run_id):
            self.reads += 1
            return {"id": run_id}

        def get_run_url(self, run):
            self.urls += 1
            return "https://smith.test/runs/" + run["id"]

    client = FakeClient()
    monkeypatch.setattr(config, "LANGSMITH_TRACING", True)
    monkeypatch.setattr(config, "LANGSMITH_API_KEY", "test-key")
    monkeypatch.setattr(tracing, "_client", client)
    tracing._trace_urls.clear()
    tracing._trace_futures.clear()

    assert tracing.trace_url("run-1") is None
    url = None
    for _ in range(50):
        url = tracing.trace_url("run-1")
        if url:
            break
        time.sleep(0.01)

    assert url == "https://smith.test/runs/run-1"
    assert tracing.trace_url("run-1") == url
    assert client.reads == 1
    assert client.urls == 1