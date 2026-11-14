"""Document shapes shared by every worker. Change these only with both humans in the loop.

The source of truth for meaning is docs/CONTRACTS.md. Keep the two in sync.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


def now():
    return datetime.now(timezone.utc)


class StepStatus(str, Enum):
    PLANNED = "planned"    # we intend to do it
    SENT = "sent"          # request left the agent, outcome unknown
    VERIFIED = "verified"  # the target system itself confirmed the effect
    FAILED = "failed"      # the target system confirmed it did not take effect
    SKIPPED = "skipped"    # no longer needed after a re-plan


class Step(BaseModel):
    run_id: str
    seq: int
    action: str                     # for example "reserve_storage"
    system: str                     # "carrier" | "warehouse" | "hospital"
    idempotency_key: str            # stable across retries and restarts
    status: StepStatus = StepStatus.PLANNED
    request: dict[str, Any] = Field(default_factory=dict)
    evidence: Optional[dict[str, Any]] = None  # raw response from the verifying read
    verified_by: Optional[str] = None           # which read proved it, in words
    reason: str = ""                             # why the agent chose this step
    authorized_by: str = "agent"                # worker id, or the human who approved
    attempts: int = 0
    lease_owner: Optional[str] = None
    lease_expires: Optional[datetime] = None
    token: int = 0                               # fencing token, see HANDOFF stretch goals
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)


class Memory(BaseModel):
    kind: str                       # "incident_fix" | "approved_rule"
    system: str
    summary: str                    # the text that gets embedded
    fix: dict[str, Any] = Field(default_factory=dict)
    source_run_id: Optional[str] = None
    approved_by: Optional[str] = None
    superseded_by: Optional[str] = None  # set when a human corrects this memory
    embedding: list[float] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=now)


class Event(BaseModel):
    run_id: str
    ts: datetime = Field(default_factory=now)
    worker: str = "agent"
    kind: str                       # "plan" | "send" | "verify" | "resume" | "memory_hit" | "chaos" ...
    message: str                    # one line, shown in the UI log
    data: dict[str, Any] = Field(default_factory=dict)
