from pathlib import Path

from timesheet_clerk import runtime


def test_ensure_profile_skill_registration_adds_external_dir(tmp_path, monkeypatch):
    state = tmp_path / ".hermes" / "timesheet-clerk"
    profile = tmp_path / ".hermes" / "profiles" / "worker"
    profile.mkdir(parents=True)
    config = profile / "config.yaml"
    config.write_text("timezone: Europe/Amsterdam\nskills:\n  disabled:\n    - something\ncron:\n  enabled: true\n", encoding="utf-8")

    monkeypatch.setenv("TIMESHEET_CLERK_STATE_DIR", str(state))
    result = runtime.ensure_profile_skill_registration("worker")
    text = config.read_text(encoding="utf-8")

    assert result["changed"] is True
    assert "skills:\n  external_dirs:\n" in text
    assert f"    - {state}" in text
    assert "  disabled:\n    - something" in text
    assert "cron:\n  enabled: true" in text


def test_profile_skill_registration_is_idempotent(tmp_path, monkeypatch):
    state = tmp_path / ".hermes" / "timesheet-clerk"
    profile = tmp_path / ".hermes" / "profiles" / "worker"
    profile.mkdir(parents=True)
    config = profile / "config.yaml"
    config.write_text(f"skills:\n  external_dirs:\n    - {state}\n", encoding="utf-8")
    monkeypatch.setenv("TIMESHEET_CLERK_STATE_DIR", str(state))

    result = runtime.ensure_profile_skill_registration("worker")
    assert result["changed"] is False
    assert config.read_text(encoding="utf-8").count(str(state)) == 1
