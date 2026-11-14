"""Shared plumbing for the three mock systems. Owner: MOCKS.

Each mock is a separate FastAPI process with its own in-memory state. They do NOT read or
write Atlas. That separation is what makes them "other people's systems" in the demo.

All state lives in app.state.store (cleared by /admin/reset). Faults and idempotency apply to
writes (POST/PUT) only, so the verifying reads always tell the truth.
"""
import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, Request, Response
from pydantic import BaseModel

SEED = Path(__file__).resolve().parent.parent / "data" / "seed"


def seed(name: str) -> dict:
    return json.loads((SEED / name).read_text())


class Faults(BaseModel):
    drop_next_responses: int = 0   # do the work, then return a 504. The key "sent, not known" case.
    fail_next_requests: int = 0    # reject before doing any work
    delay_ms: int = 0


def make_app(name: str) -> FastAPI:
    app = FastAPI(title="ColdTrace mock: " + name)
    app.state.faults = Faults()
    app.state.store = {}

    @app.middleware("http")
    async def faults_and_idempotency(request: Request, call_next):
        path = request.url.path
        if path.startswith("/admin") or path == "/health":
            return await call_next(request)
        f, store = app.state.faults, app.state.store
        if f.delay_ms:
            await asyncio.sleep(f.delay_ms / 1000)
        if request.method not in ("POST", "PUT"):
            return await call_next(request)
        key = request.headers.get("Idempotency-Key")
        if not key:
            return Response(
                json.dumps({"error": "Idempotency-Key header is required"}),
                400,
                media_type="application/json",
            )
        if f.fail_next_requests > 0:  # rejected before any work
            f.fail_next_requests -= 1
            return Response(json.dumps({"error": "injected failure"}), 503, media_type="application/json")
        cache = store.setdefault("idem", {})
        ck = (request.method, path, key)
        if key and ck in cache:  # replay the first result, create nothing
            status, body = cache[ck]
            resp = Response(body, status, media_type="application/json")
        else:
            real = await call_next(request)
            body = b"".join([c async for c in real.body_iterator])
            if key and real.status_code < 500:
                cache[ck] = (real.status_code, body)
            resp = Response(body, real.status_code, media_type="application/json")
        if f.drop_next_responses > 0:  # the work is done, the caller never hears
            f.drop_next_responses -= 1
            return Response(json.dumps({"error": "gateway timeout (injected)"}), 504, media_type="application/json")
        return resp

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
