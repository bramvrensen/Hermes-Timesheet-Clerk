from pathlib import Path


def test_single_task_booking_does_not_declare_nested_streamlit_dialog():
    source = (Path(__file__).resolve().parents[1] / "timesheet_clerk" / "ui_single_booking.py").read_text(encoding="utf-8")
    assert "@st.dialog" not in source
    assert "_render_booking_confirmation" in source
    assert "show-book-confirm-" in source
