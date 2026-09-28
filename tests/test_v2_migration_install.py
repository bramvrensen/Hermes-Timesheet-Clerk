import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile

import pytest

from timesheet_clerk.contracts import new_plan_skeleton
from timesheet_clerk.migration import export_state, import_state
from timesheet_clerk.storage import PlanRepository, StateConflict


def source_state(path):
    repo = PlanRepository(path)
    plan = new_plan_skeleton(plan_id="existing", monday="2026-08-24", sunday="2026-08-30")
    repo.create(plan)
    repo.write_receipt({"plan_id": "existing", "entry_id": "e1", "timestamp": "2026-08-24T12:00:00Z", "simplicate_response": {"id": "hours:1"}})
    (path / "SKILL.md").write_text("My Timesheet Clerk rules\n")
    (path / "config.json").write_text('{"planner_profile":"atlas","contract_hours_default":32}')
    (path / ".env").write_text("SECRET=do-not-migrate\n")
    return repo


@pytest.mark.parametrize("archive", [False, True])
def test_migration_preserves_plans_receipts_and_policy_without_hermes_secrets(tmp_path, archive):
    original = tmp_path / "old"
    repo = source_state(original)
    before = {p.relative_to(original): p.read_bytes() for p in original.rglob("*") if p.is_file() and not p.name.startswith(".")}
    source = export_state(original, tmp_path / "state.tar.gz") if archive else original
    destination = tmp_path / "new"
    result = import_state(source, destination)
    assert result["source_preserved"] is True
    for name, content in before.items():
        assert (destination / name).read_bytes() == content
        assert (original / name).read_bytes() == content
    assert not (destination / ".env").exists()
    assert PlanRepository(destination).get_active()["plan_id"] == "existing"
    with pytest.raises(StateConflict, match="empty"):
        import_state(source, destination)


def test_migration_rejects_unsafe_archives_without_partial_import(tmp_path):
    source = tmp_path / "unsafe.tar.gz"
    with tarfile.open(source, "w:gz") as archive:
        member = tarfile.TarInfo("../escape.json")
        member.size = 2
        archive.addfile(member, io.BytesIO(b"{}"))
    destination = tmp_path / "new"
    with pytest.raises(ValueError, match="Unsafe"):
        import_state(source, destination)
    assert not (tmp_path / "escape.json").exists()
    assert list(destination.iterdir()) == [destination / ".state.lock"]


def test_interrupted_import_can_resume_without_overwriting_existing_files(tmp_path, monkeypatch):
    import timesheet_clerk.migration as migration
    original = tmp_path / "old"
    source_state(original)
    destination = tmp_path / "new"
    replace = migration.os.replace
    interrupted = False
    def interrupt(source, target):
        nonlocal interrupted
        if Path(target).name == "plans" and not interrupted:
            interrupted = True
            raise OSError("Simulated interrupted migration")
        return replace(source, target)
    monkeypatch.setattr(migration.os, "replace", interrupt)
    with pytest.raises(OSError, match="interrupted"):
        import_state(original, destination)
    assert (destination / ".import-pending.json").exists()
    result = import_state(original, destination)
    assert result["source_preserved"]
    assert PlanRepository(destination).get_active()["plan_id"] == "existing"
    assert not (destination / ".import-pending.json").exists()


def installer_module():
    path = Path(__file__).resolve().parents[1] / "deploy/install.py"
    spec = importlib.util.spec_from_file_location("timesheet_installer", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_install_update_reuses_private_settings_and_persistent_volumes(tmp_path, monkeypatch):
    installer = installer_module()
    source = tmp_path / "source"
    source.mkdir()
    (source / "compose.yaml").write_text("name: timesheet-clerk-v2\n")
    settings = tmp_path / "settings.env"
    settings.write_text("TIMESHEET_CLERK_UI_PASSWORD=private\n")
    calls = []
    monkeypatch.setattr(installer.subprocess, "run", lambda args, **kwargs: calls.append((args, kwargs)))
    target = tmp_path / "install"
    installer.install(source, target, "a" * 40, env_file=settings, yes=True)
    (target / ".env").write_text("KEEP=custom\n")
    installer.install(source, target, "b" * 40, yes=True)
    assert (target / ".env").read_text() == "KEEP=custom\n"
    assert (target / ".env").stat().st_mode & 0o777 == 0o600
    assert (target / "current").resolve().name == "b" * 40
    assert (target / "releases" / ("a" * 40)).exists()
    assert not any("down" in args or "--volumes" in args for args, kwargs in calls)
    assert all(kwargs["env"]["TIMESHEET_CLERK_ENV_FILE"] == str(target / ".env") for args, kwargs in calls)


def test_env_file_keeps_dollar_signs_literal_and_rejects_newlines():
    installer = installer_module()
    text = installer.env_text({"SECRET": "abc$def#123"})
    assert "SECRET='abc$def#123'" in text
    with pytest.raises(ValueError):
        installer.env_text({"SECRET": "first\nsecond"})


def test_failed_update_restores_previous_service_and_pointer(tmp_path, monkeypatch):
    installer = installer_module()
    source = tmp_path / "source"
    source.mkdir()
    (source / "compose.yaml").write_text("name: timesheet-clerk-v2\n")
    settings = tmp_path / "private.env"
    settings.write_text("TEST=value\n")
    target = tmp_path / "install"
    monkeypatch.setattr(installer.subprocess, "run", lambda *a, **k: None)
    installer.install(source, target, "a" * 40, env_file=settings, yes=True)
    attempts = []
    def run(args, **kwargs):
        attempts.append((args, kwargs["env"]["TIMESHEET_CLERK_IMAGE_TAG"]))
        if "up" in args and kwargs["env"]["TIMESHEET_CLERK_IMAGE_TAG"] == "b" * 12:
            raise subprocess.CalledProcessError(1, args)
    monkeypatch.setattr(installer.subprocess, "run", run)
    with pytest.raises(subprocess.CalledProcessError):
        installer.install(source, target, "b" * 40, yes=True)
    assert (target / "current").resolve().name == "a" * 40
    assert any("up" in args and tag == "a" * 12 for args, tag in attempts)
