import pytest

from timesheet_clerk.fresh_start import fresh_start_week
from timesheet_clerk.storage import PlanRepository, StateConflict


def test_legacy_fresh_start_is_permanently_non_destructive(tmp_path):
    repo = PlanRepository(tmp_path)
    with pytest.raises(StateConflict, match="removed in Timesheet Clerk 0.6"):
        fresh_start_week(repo, monday="2026-08-24", sunday="2026-08-30")
