"""The excursion clock. Owner: CORE.

The budget burns while the shipment is disrupted: from the moment the agent sees that its route is gone
until the recovery is verified complete. It does not burn at rest or after recovery.
Real seconds are scaled up (config.CLOCK_MINUTES_PER_SECOND) so a three minute demo shows the clock move.
"""
from datetime import datetime, timezone

from core import config


def _utc(ts: datetime) -> datetime:
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)  # pymongo returns naive UTC


def burned_minutes(runs, now: datetime | None = None) -> int:
    """Budget minutes used so far across these run documents. A run burns from burn_started_at to burn_stopped_at."""
    now = now or datetime.now(timezone.utc)
    seconds = 0.0
    for run in runs:
        started, stopped = run.get("burn_started_at"), run.get("burn_stopped_at")
        if isinstance(started, datetime):
            end = _utc(stopped) if isinstance(stopped, datetime) else now
            seconds += max(0.0, (end - _utc(started)).total_seconds())
    return int(seconds * config.CLOCK_MINUTES_PER_SECOND)
