"""Persistent state for Timesheet Clerk.

Mutable state lives under HERMES_HOME (or TIMESHEET_CLERK_STATE_DIR), never in
the plugin installation directory, so plugin updates cannot overwrite plans or
learning history.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

from .contracts import ContractError, utc_now, validate_feedback_event, validate_plan


class StateConflict(RuntimeError):
    pass


class PlanNotFound(FileNotFoundError):
    pass


def default_state_dir() -> Path:
    configured = str(os.environ.get("TIMESHEET_CLERK_STATE_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser()
    hermes_home = str(os.environ.get("HERMES_HOME") or "").strip()
    base = Path(hermes_home).expanduser() if hermes_home else Path.home() / ".hermes"
    return base / "timesheet-clerk"


class PlanRepository:
    def __init__(self, root: Path | str | None = None):
        self.root = Path(root) if root is not None else default_state_dir()
        self.plans_dir = self.root / "plans"
        self.approvals_dir = self.root / "approvals"
        self.receipts_dir = self.root / "receipts"
        self.feedback_file = self.root / "feedback_events.jsonl"
        self.rules_file = self.root / "rules.json"
        self.active_file = self.root / "active_plan.json"
        for path in (self.plans_dir, self.approvals_dir, self.receipts_dir):
            path.mkdir(parents=True, exist_ok=True)

    def create(self, plan: dict[str, Any], *, make_active: bool = True) -> dict[str, Any]:
        candidate = validate_plan(plan)
        plan_id = candidate["plan_id"]
        if self._revision_path(plan_id, 1).exists():
            raise StateConflict(f"plan already exists: {plan_id}")
        if candidate["revision"] != 1:
            raise StateConflict("a new plan must start at revision 1")
        self._write_revision(candidate)
        if make_active:
            self._write_active_pointer(candidate)
        return deepcopy(candidate)

    def save_revision(
        self,
        plan: dict[str, Any],
        *,
        expected_revision: int,
        make_active: bool = True,
    ) -> dict[str, Any]:
        candidate = validate_plan(plan)
        plan_id = candidate["plan_id"]
        current = self.get_latest(plan_id)
        if current["revision"] != expected_revision:
            raise StateConflict(
                f"revision conflict for {plan_id}: expected {expected_revision}, current {current['revision']}"
            )
        if current["status"] in {"APPROVED", "BOOKING", "BOOKED", "SUPERSEDED"}:
            raise StateConflict(f"plan {plan_id} cannot be revised from status {current['status']}")
        candidate["revision"] = expected_revision + 1
        candidate["updated_at"] = utc_now()
        self._write_revision(candidate)
        if make_active:
            self._write_active_pointer(candidate)
        return deepcopy(candidate)

    def get_latest(self, plan_id: str) -> dict[str, Any]:
        revisions = self._revision_paths(plan_id)
        if not revisions:
            raise PlanNotFound(plan_id)
        return _read_json(revisions[-1])

    def get_revision(self, plan_id: str, revision: int) -> dict[str, Any]:
        path = self._revision_path(plan_id, revision)
        if not path.exists():
            raise PlanNotFound(f"{plan_id} revision {revision}")
        return _read_json(path)

    def get_active(self) -> dict[str, Any]:
        if not self.active_file.exists():
            raise PlanNotFound("no active plan")
        pointer = _read_json(self.active_file)
        return self.get_revision(pointer["plan_id"], int(pointer["revision"]))

    def list_plans(self, *, limit: int = 20) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if not self.plans_dir.exists():
            return rows
        for directory in self.plans_dir.iterdir():
            if not directory.is_dir():
                continue
            try:
                plan = self.get_latest(directory.name)
            except (PlanNotFound, json.JSONDecodeError, KeyError):
                continue
            rows.append({
                "plan_id": plan["plan_id"],
                "revision": plan["revision"],
                "status": plan["status"],
                "week": plan["week"],
                "target_hours": plan["target_hours"],
                "updated_at": plan.get("updated_at") or plan.get("generated_at"),
            })
        rows.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
        return rows[: max(1, limit)]

    def mark_in_review(self, plan_id: str, revision: int) -> dict[str, Any]:
        plan = self.get_revision(plan_id, revision)
        self._assert_active(plan_id, revision)
        if plan["status"] not in {"DRAFT", "IN_REVIEW"}:
            raise StateConflict(f"cannot review plan in status {plan['status']}")
        if plan["status"] == "IN_REVIEW":
            return plan
        plan["status"] = "IN_REVIEW"
        return self.save_revision(plan, expected_revision=revision)

    def approve_snapshot(self, plan_id: str, revision: int) -> dict[str, Any]:
        """Create an immutable approved snapshot after optimistic-lock checking."""
        self._assert_active(plan_id, revision)
        plan = validate_plan(self.get_revision(plan_id, revision))
        if plan["status"] not in {"DRAFT", "IN_REVIEW"}:
            raise StateConflict(f"cannot approve plan in status {plan['status']}")
        _validate_review_ready(plan)
        snapshot = deepcopy(plan)
        snapshot["status"] = "APPROVED"
        snapshot["approved_at"] = utc_now()
        path = self.approvals_dir / f"{_safe_id(plan_id)}-r{revision:04d}.json"
        if path.exists():
            existing = _read_json(path)
            if existing != snapshot:
                raise StateConflict("approval snapshot already exists with different content")
            return existing
        _atomic_write_json(path, snapshot)
        return snapshot

    def append_feedback(self, event: dict[str, Any]) -> dict[str, Any]:
        payload = validate_feedback_event(event)
        self.feedback_file.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
        with self.feedback_file.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        return deepcopy(payload)

    def feedback(self, *, plan_id: str | None = None, entry_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        if not self.feedback_file.exists():
            return []
        rows: list[dict[str, Any]] = []
        with self.feedback_file.open("r", encoding="utf-8") as handle:
            for raw in handle:
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if plan_id and event.get("plan_id") != plan_id:
                    continue
                if entry_id and event.get("entry_id") != entry_id:
                    continue
                rows.append(event)
        return rows[-max(1, limit):]

    def read_rules(self) -> list[dict[str, Any]]:
        if not self.rules_file.exists():
            return []
        payload = _read_json(self.rules_file)
        return payload if isinstance(payload, list) else []

    def write_rules(self, rules: list[dict[str, Any]]) -> None:
        """Persist agent-derived rules. This method does not infer or promote rules."""
        if not isinstance(rules, list):
            raise ContractError("rules must be an array")
        _atomic_write_json(self.rules_file, rules)

    def write_receipt(self, receipt: dict[str, Any]) -> Path:
        for key in ("plan_id", "entry_id", "timestamp"):
            if not str(receipt.get(key) or "").strip():
                raise ContractError(f"receipt.{key} is required")
        name = f"{_safe_id(receipt['plan_id'])}-{_safe_id(receipt['entry_id'])}-{uuid.uuid4().hex}.json"
        path = self.receipts_dir / name
        _atomic_write_json(path, receipt)
        return path

    def _assert_active(self, plan_id: str, revision: int) -> None:
        active = self.get_active()
        if active["plan_id"] != plan_id or active["revision"] != revision:
            raise StateConflict(
                f"opened plan {plan_id} r{revision} is no longer active; active is {active['plan_id']} r{active['revision']}"
            )

    def _write_revision(self, plan: dict[str, Any]) -> None:
        path = self._revision_path(plan["plan_id"], int(plan["revision"]))
        if path.exists():
            raise StateConflict(f"revision already exists: {plan['plan_id']} r{plan['revision']}")
        _atomic_write_json(path, plan)

    def _write_active_pointer(self, plan: dict[str, Any]) -> None:
        _atomic_write_json(self.active_file, {
            "plan_id": plan["plan_id"],
            "revision": plan["revision"],
            "updated_at": utc_now(),
        })

    def _revision_path(self, plan_id: str, revision: int) -> Path:
        directory = self.plans_dir / _safe_id(plan_id)
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"revision-{revision:04d}.json"

    def _revision_paths(self, plan_id: str) -> list[Path]:
        directory = self.plans_dir / _safe_id(plan_id)
        if not directory.exists():
            return []
        return sorted(directory.glob("revision-*.json"))


def _validate_review_ready(plan: dict[str, Any]) -> None:
    for entry in plan["entries"]:
        if entry.get("ignored") or entry.get("review_state") == "skipped":
            continue
        tier = entry.get("tier") or entry.get("overall_tier")
        if tier in {"PROPOSE", "ASK"} and entry.get("review_state") not in {"confirmed", "corrected"}:
            raise StateConflict(f"entry {entry['entry_id']} still requires review")


def _safe_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text or any(ch in text for ch in ("/", "\\", "..")):
        raise ContractError(f"unsafe id: {value!r}")
    return text


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
