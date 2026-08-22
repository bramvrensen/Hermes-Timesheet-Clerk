"""Mutable Timesheet Clerk runtime settings, skill state and profile wiring."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .storage import FILE_MODE, _mkdir, _normalize_path, default_state_dir

DEFAULT_CONFIG: dict[str, Any] = {
    "planner_profile": "atlas",
    "contract_hours_default": 36.0,
    "auto_confidence_threshold": 0.90,
    "propose_confidence_threshold": 0.65,
    "semantic_similarity_auto_allowed": False,
    "require_strong_evidence_for_auto": True,
    "prefer_planned_assignment": True,
    "preferred_hour_type": "Senior Consultant",
    "booked_artifact_retention_days": 365,
    "purge_after_successful_booking": True,
    "keep_feedback_forever": True,
    "keep_rules_forever": True,
}

_GUARDS = [
    (
        "<!-- timesheet-clerk-runtime-guard:0.4.1 -->",
        """
<!-- timesheet-clerk-runtime-guard:0.4.1 -->
## Mandatory Timesheet Clerk state-access guard
Timesheet Clerk state must be accessed only through the `timesheet_*` Clerk tools. Never read, search, infer or edit Clerk plan/config/SKILL state through filesystem, terminal, shell, generic file tools or guessed paths. Clockify date-range tool arguments must be full ISO-8601 timestamps rather than bare calendar dates.
""",
    ),
    (
        "<!-- timesheet-clerk-runtime-guard:0.4.3 -->",
        """
<!-- timesheet-clerk-runtime-guard:0.4.3 -->
## Mandatory efficient sync and source-integrity guard
For an existing week, call `timesheet_sync_probe` first. If it reports `has_changes: false`, stop without loading Simplicate, learning context, Clockify again or the full plan, and present only its deterministic summary. If changes exist, work from the returned new/changed Clockify rows. Treat each Clockify row as an immutable source bundle: ID, description, client, project, start, end and duration must never be mixed across rows. Use tool-provided summaries (`timesheet_sync_probe`, `timesheet_plan_sync`, `timesheet_plan_summary`) as authoritative; never recalculate counts or totals in the LLM response.
""",
    ),
    (
        "<!-- timesheet-clerk-runtime-guard:0.4.4 -->",
        """
<!-- timesheet-clerk-runtime-guard:0.4.4 -->
## Source baseline and update guard
`timesheet_sync_probe` compares immutable per-Clockify source snapshots. If it reports `requires_rebaseline: true`, do not treat legacy aggregate plan fields as Clockify changes. Establish a fresh Clockify source baseline for the same week while preserving all existing human review decisions, then synchronize once. A probe immediately after that sync must be a no-op unless Clockify actually changed. For future plugin upgrades prefer the Timesheet Clerk update tool rather than ad-hoc Docker/container restarts.
""",
    ),
]


def state_root() -> Path:
    root = default_state_dir()
    _mkdir(root, root=root)
    return root


def config_path() -> Path:
    return state_root() / "config.json"


def runtime_skill_path() -> Path:
    return state_root() / "SKILL.md"


def hermes_root() -> Path:
    """Global Hermes state root, independent from planner profile."""
    return state_root().parent


def profile_home(profile: str) -> Path:
    return hermes_root() / "profiles" / str(profile).strip()


def profile_config_path(profile: str) -> Path:
    return profile_home(profile) / "config.yaml"


def read_config() -> dict[str, Any]:
    result = deepcopy(DEFAULT_CONFIG)
    path = config_path()
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            payload = {}
        if isinstance(payload, dict):
            result.update(payload)
    result = validate_config(result)
    os.environ["TIMESHEET_CLERK_PLANNER_PROFILE"] = result["planner_profile"]
    return result


def write_config(config: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(DEFAULT_CONFIG)
    merged.update(config or {})
    merged = validate_config(merged)
    _atomic_write_text(config_path(), json.dumps(merged, ensure_ascii=False, indent=2) + "\n")
    os.environ["TIMESHEET_CLERK_PLANNER_PROFILE"] = merged["planner_profile"]
    ensure_profile_skill_registration(merged["planner_profile"])
    return merged


def validate_config(config: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(config)
    result["planner_profile"] = str(result.get("planner_profile") or "atlas").strip() or "atlas"
    result["contract_hours_default"] = max(0.0, float(result.get("contract_hours_default", 36.0)))
    result["auto_confidence_threshold"] = _fraction(result.get("auto_confidence_threshold"), 0.90)
    result["propose_confidence_threshold"] = _fraction(result.get("propose_confidence_threshold"), 0.65)
    if result["propose_confidence_threshold"] > result["auto_confidence_threshold"]:
        raise ValueError("propose_confidence_threshold cannot exceed auto_confidence_threshold")
    result["semantic_similarity_auto_allowed"] = bool(result.get("semantic_similarity_auto_allowed", False))
    result["require_strong_evidence_for_auto"] = bool(result.get("require_strong_evidence_for_auto", True))
    result["prefer_planned_assignment"] = bool(result.get("prefer_planned_assignment", True))
    result["preferred_hour_type"] = str(result.get("preferred_hour_type") or "").strip()
    result["booked_artifact_retention_days"] = max(1, int(result.get("booked_artifact_retention_days", 365)))
    result["purge_after_successful_booking"] = bool(result.get("purge_after_successful_booking", True))
    result["keep_feedback_forever"] = bool(result.get("keep_feedback_forever", True))
    result["keep_rules_forever"] = bool(result.get("keep_rules_forever", True))
    return result


def ensure_runtime_skill(default_skill: Path) -> Path:
    target = runtime_skill_path()
    if not target.exists():
        _mkdir(target.parent, root=state_root())
        shutil.copyfile(default_skill, target)
        _normalize_path(target, directory=False, root=state_root())
    try:
        current = target.read_text(encoding="utf-8")
    except OSError:
        current = ""
    changed = False
    for marker, text in _GUARDS:
        if current and marker not in current:
            current = current.rstrip() + "\n\n" + text.strip() + "\n"
            changed = True
    if changed:
        _atomic_write_text(target, current)
    return target


def read_runtime_skill(default_skill: Path) -> str:
    return ensure_runtime_skill(default_skill).read_text(encoding="utf-8")


def write_runtime_skill(text: str, default_skill: Path) -> Path:
    if not str(text or "").strip():
        raise ValueError("SKILL.md cannot be empty")
    target = ensure_runtime_skill(default_skill)
    _atomic_write_text(target, text.rstrip() + "\n")
    return target


def ensure_profile_skill_registration(profile: str) -> dict[str, Any]:
    """Ensure a planner profile discovers the shared runtime SKILL.

    This edits only the `skills.external_dirs` part of the profile YAML and
    deliberately avoids serializing/reformatting the rest of config.yaml.
    """
    profile = str(profile or "").strip()
    if not profile:
        raise ValueError("planner profile is required")
    path = profile_config_path(profile)
    if not path.is_file():
        raise FileNotFoundError(f"Hermes profile config not found: {path}")
    target = str(state_root())
    text = path.read_text(encoding="utf-8")
    if target in text:
        return {"profile": profile, "config": str(path), "external_dir": target, "changed": False}

    lines = text.splitlines()
    skills_index = next((i for i, line in enumerate(lines) if line.strip() == "skills:" and not line.startswith((" ", "\t"))), None)
    if skills_index is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend(["skills:", "  external_dirs:", f"    - {target}"])
    else:
        section_end = len(lines)
        for i in range(skills_index + 1, len(lines)):
            if lines[i].strip() and not lines[i].startswith((" ", "\t")):
                section_end = i
                break
        external_index = next(
            (i for i in range(skills_index + 1, section_end) if lines[i].strip().startswith("external_dirs:")),
            None,
        )
        if external_index is None:
            lines[skills_index + 1:skills_index + 1] = ["  external_dirs:", f"    - {target}"]
        elif lines[external_index].strip() in {"external_dirs: []", "external_dirs:[]"}:
            indent = lines[external_index][: len(lines[external_index]) - len(lines[external_index].lstrip())]
            lines[external_index:external_index + 1] = [f"{indent}external_dirs:", f"{indent}  - {target}"]
        else:
            indent = lines[external_index][: len(lines[external_index]) - len(lines[external_index].lstrip())]
            lines.insert(external_index + 1, f"{indent}  - {target}")

    # Write in-place to preserve the profile config's existing ownership.
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return {"profile": profile, "config": str(path), "external_dir": target, "changed": True}


def reload_skills_for_profile(profile: str) -> dict[str, Any]:
    """Call Hermes' real skill reload function in the requested profile context."""
    registration = ensure_profile_skill_registration(profile)
    env = os.environ.copy()
    env["HERMES_HOME"] = str(profile_home(profile))
    code = (
        "import json; from agent.skill_commands import reload_skills; "
        "r=reload_skills(); print(json.dumps(r, default=str))"
    )
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"skill reload exited {result.returncode}")
    try:
        payload = json.loads(result.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        payload = {"raw": result.stdout.strip()}
    return {"registration": registration, "reload": payload}


def purge_expired_artifacts(root: Path | None = None, *, now: datetime | None = None) -> dict[str, int]:
    base = Path(root) if root is not None else state_root()
    config = read_config()
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=config["booked_artifact_retention_days"])
    removed = {"approvals": 0, "receipts": 0}
    for key, directory_name in (("approvals", "approvals"), ("receipts", "receipts")):
        directory = base / directory_name
        if not directory.exists():
            continue
        for path in directory.glob("*.json"):
            try:
                modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            except OSError:
                continue
            if modified < cutoff:
                try:
                    path.unlink()
                    removed[key] += 1
                except OSError:
                    pass
    return removed


def _fraction(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if number > 1.0:
        number /= 100.0
    return min(1.0, max(0.0, number))


def _atomic_write_text(path: Path, text: str) -> None:
    root = state_root()
    _mkdir(path.parent, root=root)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        os.fchmod(fd, FILE_MODE)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
        _normalize_path(path, directory=False, root=root)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
