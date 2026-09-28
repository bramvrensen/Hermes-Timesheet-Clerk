"""Non-destructive export/import of Timesheet Clerk state, never Hermes state."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile

from .contracts import validate_plan
from .locking import state_lock
from .storage import StateConflict, _atomic_write_json, repair_shared_permissions

FILES = {"config.json", "SKILL.md", "active_plan.json", "feedback_events.jsonl", "rules.json"}
DIRECTORIES = {"plans", "approvals", "receipts", "booking_attempts"}


def _validate(stage: Path) -> None:
    for directory in ("plans", "approvals"):
        for path in (stage / directory).rglob("*.json") if (stage / directory).exists() else []:
            validate_plan(json.loads(path.read_text(encoding="utf-8")))
    for path in stage.rglob("*.json"):
        json.loads(path.read_text(encoding="utf-8"))
    feedback = stage / "feedback_events.jsonl"
    if feedback.exists():
        for line in feedback.read_text(encoding="utf-8").splitlines():
            if line.strip():
                json.loads(line)


def _copy_directory(source: Path, stage: Path) -> None:
    for path in source.rglob("*"):
        if path.is_symlink():
            raise ValueError("State migration refuses symlinks")
    for name in FILES | DIRECTORIES:
        path = source / name
        if path.is_dir():
            shutil.copytree(path, stage / name)
        elif path.is_file():
            shutil.copy2(path, stage / name)


def _unpack(source: Path, stage: Path) -> None:
    with tarfile.open(source, "r:gz") as archive:
        total = 0
        for member in archive:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or not path.parts:
                raise ValueError("Unsafe Timesheet Clerk archive path")
            if path.parts[0] not in FILES | DIRECTORIES:
                raise ValueError(f"Unexpected file in Timesheet Clerk archive: {path.parts[0]}")
            if not (member.isfile() or member.isdir()):
                raise ValueError("Timesheet Clerk archives may contain only regular files and directories")
            total += member.size
            if total > 1024 * 1024 * 1024:
                raise ValueError("Timesheet Clerk archive exceeds 1 GiB")
            target = stage.joinpath(*path.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                handle = archive.extractfile(member)
                if handle is None:
                    raise ValueError("Unreadable Timesheet Clerk archive member")
                with handle, target.open("wb") as output:
                    shutil.copyfileobj(handle, output)


def export_state(source: Path, destination: Path) -> Path:
    source, destination = Path(source), Path(destination)
    if not source.is_dir():
        raise ValueError("Timesheet Clerk source state directory does not exist")
    with state_lock(source):
        with destination.open("xb") as handle:
            os.chmod(destination, 0o600)
            with tarfile.open(fileobj=handle, mode="w:gz") as archive:
                for name in sorted(FILES | DIRECTORIES):
                    path = source / name
                    if path.exists():
                        if path.is_symlink() or any(p.is_symlink() for p in path.rglob("*")):
                            raise ValueError("State export refuses symlinks")
                        archive.add(path, arcname=name)
    return destination


def import_state(source: Path, destination: Path) -> dict:
    """Validate before mutation; resume an interrupted move from its journal."""
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or source in destination.parents or destination in source.parents:
        raise ValueError("Timesheet Clerk source and destination must be separate")
    destination.mkdir(parents=True, exist_ok=True)
    with state_lock(destination):
        pending = destination / ".import-pending.json"
        if pending.exists():
            journal = json.loads(pending.read_text(encoding="utf-8"))
            if journal["source"] != str(source):
                raise StateConflict("An interrupted import must be resumed with the same source")
            stage = destination / journal["stage"]
            names = journal["names"]
        else:
            contents = [p.name for p in destination.iterdir() if p.name != ".state.lock"]
            if contents:
                raise StateConflict("Import requires an empty Timesheet Clerk destination; existing data is never overwritten")
            stage = Path(tempfile.mkdtemp(prefix=".import-", dir=destination))
            try:
                if source.is_dir():
                    _copy_directory(source, stage)
                elif source.is_file():
                    _unpack(source, stage)
                else:
                    raise ValueError("Timesheet Clerk migration source does not exist")
                _validate(stage)
                names = sorted(path.name for path in stage.iterdir())
                if not names:
                    raise ValueError("No Timesheet Clerk state found in the migration source")
                journal = {"source": str(source), "stage": stage.name, "names": names}
                _atomic_write_json(pending, journal, root=destination)
            except Exception:
                shutil.rmtree(stage)
                raise
        for name in names:
            path = stage / name
            if path.exists():
                if (destination / name).exists():
                    raise StateConflict("Import conflict; existing Timesheet Clerk state was preserved")
                os.replace(path, destination / name)
        shutil.rmtree(stage, ignore_errors=True)
        _atomic_write_json(destination / ".migration.json", {"source": str(source), "imported": names, "version": 2}, root=destination)
        repair_shared_permissions(destination)
        pending.unlink()
        return {"imported": names, "source_preserved": True}


def main() -> None:
    parser = argparse.ArgumentParser(description="Timesheet Clerk state migration")
    parser.add_argument("action", choices=("export", "import"))
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    result = export_state(args.source, args.destination) if args.action == "export" else import_state(args.source, args.destination)
    print(json.dumps(result, default=str))


if __name__ == "__main__":
    main()
