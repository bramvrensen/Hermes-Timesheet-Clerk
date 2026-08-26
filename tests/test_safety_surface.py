from pathlib import Path


def test_manifest_exposes_decisions_api_not_plan_write_tools():
    root = Path(__file__).resolve().parents[1]
    manifest = (root / "plugin.yaml").read_text(encoding="utf-8")
    assert "timesheet_mapping_prepare" in manifest
    assert "timesheet_mapping_apply" in manifest
    assert "timesheet_plan_create" not in manifest
    assert "timesheet_plan_sync" not in manifest
    assert "timesheet_plan_fresh_start" not in manifest
    assert "timesheet_source_rebaseline" not in manifest


def test_plugin_has_no_legacy_monkeypatch_or_destructive_tool_surface():
    root = Path(__file__).resolve().parents[1]
    source = (root / "plugin.py").read_text(encoding="utf-8")
    assert "plugin_legacy" not in source
    assert 'name="timesheet_plan_create"' not in source
    assert 'name="timesheet_plan_sync"' not in source
    assert 'name="timesheet_plan_fresh_start"' not in source
    assert 'name="timesheet_mapping_prepare"' in source
    assert 'name="timesheet_mapping_apply"' in source
