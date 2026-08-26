from pathlib import Path


def test_manifest_does_not_expose_fresh_start_tool():
    root = Path(__file__).resolve().parents[1]
    manifest = (root / "plugin.yaml").read_text(encoding="utf-8")
    assert "timesheet_plan_fresh_start" not in manifest


def test_plugin_does_not_register_fresh_start_tool():
    root = Path(__file__).resolve().parents[1]
    source = (root / "plugin.py").read_text(encoding="utf-8")
    assert 'name="timesheet_plan_fresh_start"' not in source
    assert "Deliberately DO NOT register timesheet_plan_fresh_start" in source
