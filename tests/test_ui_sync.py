from pathlib import Path

import timesheet_clerk.ui_sync as ui_sync


def test_ui_sync_does_not_import_provider_clients():
    source = Path(ui_sync.__file__).read_text(encoding="utf-8")
    assert "ClockifyClient" not in source
    assert "ClockifyConfig" not in source
    assert "Simplicate" not in source
    assert "CLOCKIFY_API_KEY" not in source


def test_launch_sync_only_starts_hermes(monkeypatch, tmp_path):
    calls = []

    class Child:
        pid = 1234

    def fake_popen(args, **kwargs):
        calls.append((args, kwargs))
        return Child()

    monkeypatch.setattr(ui_sync.subprocess, "Popen", fake_popen)
    result = ui_sync.launch_sync(root=tmp_path, profile="atlas", prompt="sync week")
    assert result["status"] == "running"
    assert result["pid"] == 1234
    assert calls[0][0][-1] == "sync week"
    assert "hermes" in calls[0][0][0]
