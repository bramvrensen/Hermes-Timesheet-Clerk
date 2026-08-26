from pathlib import Path

import timesheet_clerk.ui_sync as ui_sync


def test_launch_sync_starts_supervised_job_runner(monkeypatch, tmp_path):
    calls = []

    class Child:
        pid = 1234

    def fake_popen(args, **kwargs):
        calls.append((args, kwargs))
        return Child()

    monkeypatch.setattr(ui_sync.subprocess, "Popen", fake_popen)
    result = ui_sync.launch_sync(root=tmp_path, profile="atlas", prompt="map week")

    assert result["status"] == "RUNNING"
    assert result["pid"] == 1234
    assert result["run_id"]
    args = calls[0][0]
    assert "timesheet_clerk.job_runner" in args
    assert "atlas" in args
    assert "map week" in args


def test_dead_runner_is_reported_failed_not_finished(monkeypatch, tmp_path):
    ui_sync._write(tmp_path, {
        "run_id": "abc",
        "pid": 999,
        "profile": "atlas",
        "status": "RUNNING",
        "started_at": "2026-08-26T18:00:00+00:00",
    })
    monkeypatch.setattr(ui_sync, "_pid_running", lambda pid: False)

    status = ui_sync.sync_status(tmp_path)

    assert status["status"] == "FAILED"
    assert "disappeared" in status["message"]
    persisted = (tmp_path / "planner-sync-status.json").read_text(encoding="utf-8")
    assert '"FAILED"' in persisted
