"""Fault injector. Owner: CHAOS. Build this FIRST, it is the test harness all day.

Named events (each one is also a button in the UI):
  cancel_flight    -> POST carrier /admin/cancel_flight
  kill_agent       -> SIGKILL the pid in `workers`, then restart it after a pause
  change_carrier   -> POST carrier /admin/schema {"version": 2}
  drop_response    -> POST <system> /admin/faults {"drop_next_responses": 1}
  random           -> pick one of the above at a random moment, seeded so a run can be replayed

Every event writes an Event(kind="chaos") so the UI log shows what was done to the system.
"""

EVENTS = ["cancel_flight", "kill_agent", "change_carrier", "drop_response"]


def fire(event: str, **kwargs) -> dict:
    raise NotImplementedError


def random_run(seed: int, count: int = 5) -> list[dict]:
    raise NotImplementedError
