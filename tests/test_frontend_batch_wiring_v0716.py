from pathlib import Path


def test_review_app_uses_real_batch_booking_controls():
    root = Path(__file__).resolve().parents[1]
    source = (root / "frontend" / "review_app.py").read_text(encoding="utf-8")
    assert "from timesheet_clerk.ui_batch_booking import render_day_booking, render_week_booking" in source
    assert "with action: render_day_booking(repo,plan,day,entries)" in source
    assert "with book: render_week_booking(repo,plan)" in source
    assert 'st.button("Book day",key=f"book-{day}",disabled=True' not in source
    assert 'st.button("Book approved week",type="primary",disabled=True' not in source


def test_app_wrapper_does_not_render_second_week_booking_control():
    root = Path(__file__).resolve().parents[1]
    source = (root / "frontend" / "app.py").read_text(encoding="utf-8")
    assert "def _review_page_with_queue" in source
    assert "#### Batch booking" not in source
    assert "render_week_booking" not in source
