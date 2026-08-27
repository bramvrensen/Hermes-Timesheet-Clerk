from pathlib import Path


def test_streamlit_editor_wrapper_uses_stable_base_reference():
    source = Path("frontend/app.py").read_text(encoding="utf-8")
    assert 'if not hasattr(review, "_timesheet_clerk_base_editor")' in source
    assert 'review._timesheet_clerk_base_editor = review._editor' in source
    assert 'review._timesheet_clerk_base_editor(plan, entry)' in source
    assert '_original_editor = review._editor' not in source
