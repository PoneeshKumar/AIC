"""Shared plumbing for the three mock systems. Owner: MOCKS.

Each mock is a separate FastAPI process with its own in-memory state. They do NOT read or
write Atlas. That separation is what makes them "other people's systems" in the demo.

Already working here: /health and the fault switches under /admin/faults.
TODO(MOCKS): idempotency store (same Idempotency-Key returns the first result, creates nothing new)
TODO(MOCKS): apply faults in a middleware (drop the response AFTER the write took effect)
"""
from fastapi import FastAPI
from pydantic import BaseModel


class Faults(BaseModel):
    drop_next_responses: int = 0   # do the work, then return a 504. The key "sent, not known" case.
    fail_next_requests: int = 0    # reject before doing any work
    delay_ms: int = 0


def make_app(name: str) -> FastAPI:
    app = FastAPI(title="ColdTrace mock: " + name)
    app.state.faults = Faults()
    app.state.store = {}

    @app.get("/health")
    def health():
        return {"system": name, "ok": True}

    @app.get("/admin/faults")
    def get_faults():
        return app.state.faults

    @app.post("/admin/faults")
    def set_faults(faults: Faults):
        app.state.faults = faults
        return app.state.faults

    @app.post("/admin/reset")
    def reset():
        app.state.faults = Faults()
        app.state.store = {}
        return {"reset": True}

    return app
