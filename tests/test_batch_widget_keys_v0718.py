from pathlib import Path


def test_batch_widgets_use_explicit_scoped_keys():
    source = Path("timesheet_clerk/ui_batch_booking.py").read_text(encoding="utf-8")
    assert 'key=f"book-day-{widget_scope}-{plan[\'plan_id\']}-{day}"' in source
    assert 'key=f"book-week-{widget_scope}-{plan[\'plan_id\']}"' in source
    assert 'def render_week_booking(repo: PlanRepository, plan: dict[str, Any], *, widget_scope: str = "review")' in source


def test_booking_tab_uses_distinct_week_widget_scope():
    source = Path("timesheet_clerk/ui_booking.py").read_text(encoding="utf-8")
    assert 'render_week_booking(repo, plan, widget_scope="booking-tab")' in source
