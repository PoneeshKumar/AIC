"""Keep tests offline: the model call in agent.adapt is stubbed to fail, so propose_fix falls back to the recalled fix."""
import pytest


@pytest.fixture(autouse=True)
def no_live_llm(monkeypatch):
    from agent import adapt

    monkeypatch.setattr(adapt, "_ask_llm", lambda prompt: (_ for _ in ()).throw(RuntimeError("no live LLM in tests")))
