"""Acceptance tests. Owner: QA. Each test is one demo beat. Remove the skip as beats land."""
import pytest

pytestmark = pytest.mark.skip(reason="enable as each beat is built")


def test_happy_path_all_steps_verified():
    """Cancel the flight. Every step ends verified, budget respected, duplicates == 0."""


def test_kill_after_reserve_does_not_double_book():
    """Kill the agent right after the warehouse reservation. Restart. Reservations == 1."""


def test_dropped_response_is_resolved_by_reading():
    """Warehouse does the work but drops the response. Agent verifies by read, does not retry blindly."""


def test_schema_change_is_adapted_after_approval():
    """Carrier flips to schema v2. Agent proposes a mapping, we approve, run completes."""


def test_second_run_uses_stored_rule():
    """Same drift on a second shipment. No failure first, no approval asked."""


def test_random_chaos_fifty_runs():
    """50 seeded random runs. Invariants hold on every one."""
