"""LangSmith tracing. Off unless LANGSMITH_TRACING=true and a key is set.

Every helper is a pass-through when tracing is off, and LangSmith errors never reach the recovery loop.
Spans carry ids, budgets, route ids and response shapes only. Never put keys in a span.
"""
from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from functools import wraps

from core import config

log = logging.getLogger("coldtrace.tracing")
_client = None
_trace_urls: dict[str, str] = {}
_trace_futures: dict[str, Future] = {}
_trace_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="coldtrace-trace")


def enabled() -> bool:
  return bool(config.LANGSMITH_TRACING and config.LANGSMITH_API_KEY)


def _client_instance():
  global _client
  if _client is None:
    from langsmith import Client
    _client = Client(
      api_url=config.LANGSMITH_ENDPOINT,
      api_key=config.LANGSMITH_API_KEY,
    )
  return _client


def _safe_inputs(inputs):
  """Keep trace inputs to primitives and shapes; never serialize database records."""
  if isinstance(inputs, dict):
    return {
      key: _safe_inputs(value)
      for key, value in inputs.items()
      if key not in {"db", "run", "shipment"}
    }
  if isinstance(inputs, (list, tuple)):
    return [_safe_inputs(value) for value in inputs]
  if inputs is None or isinstance(inputs, (str, int, float, bool)):
    return inputs
  return type(inputs).__name__


def _process_inputs(inputs):
  return _safe_inputs(inputs)


def _base_metadata() -> dict:
  return {"agent_id": config.LANGSMITH_AGENT_ID, "agent_environment": config.LANGSMITH_AGENT_ENVIRONMENT}


def traced(name: str, run_type: str = "chain"):
  """Decorator. Returns the function unchanged when tracing is off."""
  def decorate(fn):
    traced_fn = None

    @wraps(fn)
    def call(*args, **kwargs):
      nonlocal traced_fn
      if not enabled():
        return fn(*args, **kwargs)
      if traced_fn is None:
        try:
          from langsmith import traceable
          traced_fn = traceable(
            name=name, run_type=run_type, metadata=_base_metadata(), tags=["coldtrace"],
            process_inputs=_process_inputs,
          )(fn)
        except Exception:
          log.warning("langsmith unavailable, tracing disabled for %s", name, exc_info=True)
          return fn(*args, **kwargs)
      return traced_fn(*args, **kwargs)

    return call
  return decorate


def span(name: str, run_type: str, fn, *args, metadata: dict | None = None, **kwargs):
  """Call fn inside a child span. Exceptions from fn propagate, tracing failures do not."""
  if not enabled():
    return fn(*args, **kwargs)
  try:
    from langsmith import traceable
    wrapped = traceable(
      name=name, run_type=run_type, metadata={**_base_metadata(), **(metadata or {})},
      tags=["coldtrace"], process_inputs=_process_inputs,
    )(fn)
  except Exception:
    log.warning("langsmith unavailable for span %s", name, exc_info=True)
    return fn(*args, **kwargs)
  return wrapped(*args, **kwargs)


def annotate(**metadata) -> None:
  """Add metadata to the current trace, if there is one."""
  if not enabled():
    return
  try:
    from langsmith.run_helpers import get_current_run_tree
    tree = get_current_run_tree()
    if tree is not None:
      tree.metadata.update(metadata)
  except Exception:
    log.debug("annotate failed", exc_info=True)


def current_run_id() -> str | None:
  if not enabled():
    return None
  try:
    from langsmith.run_helpers import get_current_run_tree
    tree = get_current_run_tree()
    return str(tree.id) if tree is not None else None
  except Exception:
    return None


def trace_url(langsmith_run_id: str | None) -> str | None:
  """A link the UI can open. Uses the SDK so it points at the right workspace."""
  if not langsmith_run_id or not enabled():
    return None
  run_id = str(langsmith_run_id)
  if run_id in _trace_urls:
    return _trace_urls[run_id]
  future = _trace_futures.get(run_id)
  if future is None:
    _trace_futures[run_id] = _trace_executor.submit(_lookup_trace_url, run_id)
    return None
  if not future.done():
    return None
  _trace_futures.pop(run_id, None)
  try:
    url = future.result()
  except Exception:
    log.debug("could not resolve LangSmith trace URL", exc_info=True)
    return None
  if url:
    _trace_urls[run_id] = url
  return url


def _lookup_trace_url(run_id: str) -> str | None:
  client = _client_instance()
  run = client.read_run(run_id)
  return client.get_run_url(run=run)


def score(langsmith_run_id: str | None, results: dict) -> None:
  """Attach pass/fail feedback (1.0 or 0.0) to the root run."""
  if not langsmith_run_id or not enabled():
    return
  try:
    client = _client_instance()
    for key, ok in results.items():
      client.create_feedback(langsmith_run_id, key=key, score=1.0 if ok else 0.0)
  except Exception:
    log.warning("could not send feedback", exc_info=True)


def flush() -> None:
  """Flush background LangSmith work for short-lived agent processes."""
  if not enabled():
    return
  try:
    client = _client_instance()
    if hasattr(client, "flush"):
      client.flush()
  except Exception:
    log.warning("could not flush LangSmith traces", exc_info=True)
