"""Keep tests offline: the model call in agent.adapt is stubbed to fail, so propose_fix falls back to the recalled fix."""
import pytest


@pytest.fixture(autouse=True)
def no_live_llm(monkeypatch):
    from agent import adapt

    monkeypatch.setattr(adapt, "_ask_llm", lambda prompt: (_ for _ in ()).throw(RuntimeError("no live LLM in tests")))


@pytest.fixture(autouse=True)
def no_demo_pacing(monkeypatch):
    """The step pause and the scaled clock are for the screen. Tests that want the clock turn it on."""
    from core import config

    monkeypatch.setattr(config, "AGENT_STEP_DELAY_S", 0)
    monkeypatch.setattr(config, "CLOCK_MINUTES_PER_SECOND", 0)


@pytest.fixture(autouse=True)
def no_real_agent(monkeypatch):
    """Approving a proposal starts the agent. Tests must never spawn one or read the real cluster."""
    from chaos import injector

    started = []
    monkeypatch.setattr(injector, "wake_agent", lambda: started.append(1))
    return started
