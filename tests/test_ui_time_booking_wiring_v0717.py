from pathlib import Path


def test_ui_time_is_presentation_only_and_does_not_shadow_booking_renderers():
    source = Path("timesheet_clerk/ui_time.py").read_text()

    assert "review._entry_summary = entry_summary" in source
    assert "review._render_day =" not in source
    assert "review._review_page =" not in source
    assert 'st.button("Book day"' not in source
    assert 'st.button("Book approved week"' not in source


def test_canonical_review_surface_owns_batch_booking_controls():
    source = Path("frontend/review_app.py").read_text()

    assert "render_day_booking(repo,plan,day,entries)" in source
    assert "render_week_booking(repo,plan)" in source
