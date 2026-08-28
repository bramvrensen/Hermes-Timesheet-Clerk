"""Persistent state for Timesheet Clerk.

Mutable state lives outside the plugin checkout. Files are shared between the
Hermes runtime and the optional UI, so writers normalize ownership to the
Hermes home owner and use group-safe permissions. Working-plan revision history
is bounded; immutable approvals, receipts and feedback remain separate.
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from .contracts import ContractError, utc_now, validate_feedback_event, validate_plan

DIR_MODE = 0o770
FILE_MODE = 0o660
DEFAULT_REVISION_RETENTION = 10


class StateConflict(RuntimeError): pass
class PlanNotFound(FileNotFoundError): pass


def default_state_dir() -> Path:
    configured = str(os.environ.get("TIMESHEET_CLERK_STATE_DIR") or "").strip()
    if configured: return Path(configured).expanduser()
    hermes_home = str(os.environ.get("HERMES_HOME") or "").strip(); base = Path(hermes_home).expanduser() if hermes_home else Path.home() / ".hermes"
    return base / "timesheet-clerk"


def _shared_owner(root: Path | None = None) -> tuple[int, int] | None:
    state = Path(root) if root is not None else default_state_dir()
    for candidate in [state.parent, Path("/home/hermes"), state]:
        try: stat = candidate.stat()
        except OSError: continue
        return stat.st_uid, stat.st_gid
    return None


def _normalize_path(path: Path, *, directory: bool, root: Path | None = None) -> None:
    try: os.chmod(path, DIR_MODE if directory else FILE_MODE)
    except OSError: pass
    owner = _shared_owner(root)
    if owner is None: return
    try: stat = path.stat()
    except OSError: return
    if (stat.st_uid, stat.st_gid) == owner: return
    if os.geteuid() == 0:
        try: os.chown(path, owner[0], owner[1])
        except OSError: pass


def _mkdir(path: Path, *, root: Path | None = None) -> None:
    path.mkdir(parents=True, exist_ok=True); _normalize_path(path, directory=True, root=root)


def repair_shared_permissions(root: Path | str | None = None) -> dict[str, int]:
    base = Path(root) if root is not None else default_state_dir()
    if not base.exists(): _mkdir(base, root=base)
    repaired = {"directories":0,"files":0}
    for path in [base,*base.rglob("*")]:
        directory=path.is_dir()
        try: stat=path.stat(); before=(stat.st_uid,stat.st_gid,stat.st_mode & 0o777)
        except OSError: continue
        _normalize_path(path,directory=directory,root=base)
        try: stat=path.stat(); after=(stat.st_uid,stat.st_gid,stat.st_mode & 0o777)
        except OSError: continue
        if before != after: repaired["directories" if directory else "files"] += 1
    return repaired


def _revision_retention() -> int:
    raw=os.environ.get("TIMESHEET_CLERK_REVISION_RETENTION",str(DEFAULT_REVISION_RETENTION))
    try:return max(2,int(raw))
    except (TypeError,ValueError):return DEFAULT_REVISION_RETENTION


def _approval_content(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Canonical immutable approval content, excluding creation timestamp metadata."""
    result=deepcopy(snapshot); result.pop("approved_at",None); return result


class PlanRepository:
    def __init__(self, root: Path | str | None = None):
        self.root=Path(root) if root is not None else default_state_dir(); self.plans_dir=self.root/"plans"; self.approvals_dir=self.root/"approvals"; self.receipts_dir=self.root/"receipts"; self.feedback_file=self.root/"feedback_events.jsonl"; self.rules_file=self.root/"rules.json"; self.active_file=self.root/"active_plan.json"; _mkdir(self.root,root=self.root)
        for path in (self.plans_dir,self.approvals_dir,self.receipts_dir): _mkdir(path,root=self.root)
        if os.geteuid()==0: repair_shared_permissions(self.root)

    def create(self, plan: dict[str, Any], *, make_active: bool = True) -> dict[str, Any]:
        candidate=validate_plan(plan); plan_id=candidate["plan_id"]
        if self._revision_path(plan_id,1).exists(): raise StateConflict(f"plan already exists: {plan_id}")
        if candidate["revision"] != 1: raise StateConflict("a new plan must start at revision 1")
        self._write_revision(candidate)
        if make_active: self._write_active_pointer(candidate)
        return deepcopy(candidate)

    def save_revision(self, plan: dict[str, Any], *, expected_revision: int, make_active: bool = True) -> dict[str, Any]:
        candidate=validate_plan(plan); plan_id=candidate["plan_id"]; current=self.get_latest(plan_id)
        if current["revision"] != expected_revision: raise StateConflict(f"revision conflict for {plan_id}: expected {expected_revision}, current {current['revision']}")
        if current["status"] in {"APPROVED","BOOKING","BOOKED","SUPERSEDED"}: raise StateConflict(f"plan {plan_id} cannot be revised from status {current['status']}")
        candidate["revision"]=expected_revision+1; candidate["updated_at"]=utc_now(); self._write_revision(candidate)
        if make_active:self._write_active_pointer(candidate)
        self.prune_working_revisions(plan_id); return deepcopy(candidate)

    def get_latest(self, plan_id: str) -> dict[str, Any]:
        revisions=self._revision_paths(plan_id)
        if not revisions: raise PlanNotFound(plan_id)
        return _read_json(revisions[-1])

    def get_revision(self, plan_id: str, revision: int) -> dict[str, Any]:
        path=self._revision_path(plan_id,revision)
        if not path.exists(): raise PlanNotFound(f"{plan_id} revision {revision}")
        return _read_json(path)

    def get_active(self) -> dict[str, Any]:
        if not self.active_file.exists(): raise PlanNotFound("no active plan")
        pointer=_read_json(self.active_file); return self.get_revision(pointer["plan_id"],int(pointer["revision"]))

    def list_plans(self, *, limit: int = 20) -> list[dict[str, Any]]:
        rows=[]
        if not self.plans_dir.exists(): return rows
        for directory in self.plans_dir.iterdir():
            if not directory.is_dir(): continue
            try: plan=self.get_latest(directory.name)
            except (PlanNotFound,json.JSONDecodeError,KeyError): continue
            rows.append({"plan_id":plan["plan_id"],"revision":plan["revision"],"status":plan["status"],"week":plan["week"],"target_hours":plan["target_hours"],"updated_at":plan.get("updated_at") or plan.get("generated_at")})
        rows.sort(key=lambda row:str(row.get("updated_at") or ""),reverse=True); return rows[:max(1,limit)]

    def prune_working_revisions(self, plan_id: str, *, keep: int | None = None) -> int:
        paths=self._revision_paths(plan_id); retention=max(2,int(keep or _revision_retention())); removed=0
        for path in paths[:-retention]:
            try:path.unlink();removed+=1
            except OSError:continue
        return removed

    def compact_all_working_revisions(self, *, keep: int | None = None) -> int:
        removed=0
        if not self.plans_dir.exists(): return removed
        for directory in self.plans_dir.iterdir():
            if directory.is_dir(): removed += self.prune_working_revisions(directory.name,keep=keep)
        return removed

    def mark_in_review(self, plan_id: str, revision: int) -> dict[str, Any]:
        plan=self.get_revision(plan_id,revision); self._assert_active(plan_id,revision)
        if plan["status"] not in {"DRAFT","IN_REVIEW"}: raise StateConflict(f"cannot review plan in status {plan['status']}")
        if plan["status"]=="IN_REVIEW": return plan
        plan["status"]="IN_REVIEW"; return self.save_revision(plan,expected_revision=revision)

    def approve_snapshot(self, plan_id: str, revision: int) -> dict[str, Any]:
        self._assert_active(plan_id,revision); plan=validate_plan(self.get_revision(plan_id,revision))
        if plan["status"] not in {"DRAFT","IN_REVIEW"}: raise StateConflict(f"cannot approve plan in status {plan['status']}")
        _validate_review_ready(plan); snapshot=deepcopy(plan); snapshot["status"]="APPROVED"; snapshot["approved_at"]=utc_now(); path=self.approvals_dir/f"{_safe_id(plan_id)}-r{revision:04d}.json"
        if path.exists():
            existing=_read_json(path)
            if _approval_content(existing) != _approval_content(snapshot): raise StateConflict("approval snapshot already exists with different plan content")
            return existing
        _atomic_write_json(path,snapshot,root=self.root); return snapshot

    def write_receipt(self, receipt: dict[str, Any]) -> Path:
        entry_id=_safe_id(str(receipt.get("entry_id") or uuid.uuid4().hex)); timestamp=_safe_id(str(receipt.get("timestamp") or utc_now())); path=self.receipts_dir/f"{timestamp}-{entry_id}.json"; _atomic_write_json(path,receipt,root=self.root); return path

    def append_feedback(self, event: dict[str, Any]) -> None:
        payload=validate_feedback_event(event); self.feedback_file.parent.mkdir(parents=True,exist_ok=True)
        with self.feedback_file.open("a",encoding="utf-8") as handle: handle.write(json.dumps(payload,sort_keys=True)+"\n")
        _normalize_path(self.feedback_file,directory=False,root=self.root)

    def _revision_path(self, plan_id: str, revision: int) -> Path: return self.plans_dir/_safe_id(plan_id)/f"revision-{revision:04d}.json"
    def _revision_paths(self, plan_id: str) -> list[Path]:
        directory=self.plans_dir/_safe_id(plan_id)
        return sorted(directory.glob("revision-*.json")) if directory.exists() else []
    def _write_revision(self, plan: dict[str, Any]) -> None:
        path=self._revision_path(plan["plan_id"],int(plan["revision"])); _mkdir(path.parent,root=self.root); _atomic_write_json(path,plan,root=self.root)
    def _write_active_pointer(self, plan: dict[str, Any]) -> None: _atomic_write_json(self.active_file,{"plan_id":plan["plan_id"],"revision":plan["revision"]},root=self.root)
    def _assert_active(self, plan_id: str, revision: int) -> None:
        active=self.get_active()
        if active["plan_id"] != plan_id or int(active["revision"]) != int(revision): raise StateConflict("requested plan revision is not active")


def _validate_review_ready(plan: dict[str, Any]) -> None:
    pending=[]
    for entry in plan.get("entries") or []:
        if entry.get("ignored") or entry.get("review_state")=="skipped": continue
        tier=entry.get("tier") or entry.get("overall_tier") or "ASK"
        if tier in {"PROPOSE","ASK"} and entry.get("review_state") not in {"confirmed","corrected"}: pending.append(entry.get("entry_id"))
    if pending: raise StateConflict(f"cannot approve: {len(pending)} entries still require review")


def _safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-","_"} else "_" for ch in value)


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r",encoding="utf-8") as handle: return json.load(handle)


def _atomic_write_json(path: Path, payload: Any, *, root: Path | None = None) -> None:
    _mkdir(path.parent,root=root or path.parent)
    fd,tmp=tempfile.mkstemp(prefix=f".{path.name}.",dir=str(path.parent))
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as handle: json.dump(payload,handle,indent=2,sort_keys=True); handle.write("\n")
        os.replace(tmp,path); _normalize_path(path,directory=False,root=root or path.parent)
    finally:
        try: os.unlink(tmp)
        except FileNotFoundError: pass
