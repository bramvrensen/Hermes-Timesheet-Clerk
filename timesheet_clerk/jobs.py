"""Independent, serialized planner jobs and persistent status."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import uuid
from zoneinfo import ZoneInfo

from .deployment import APP_ROOT, PROFILE, hermes_executable, hermes_root
from .locking import state_lock
from .storage import PlanRepository, StateConflict, _atomic_write_json


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_week(monday: str, sunday: str) -> None:
    from .orchestration import _validate_week
    _validate_week(monday, sunday)
    if date.fromisoformat(sunday) != date.fromisoformat(monday) + timedelta(days=6):
        raise ValueError("Select one complete Monday–Sunday week for Timesheet Clerk")


def job_path(root: Path, run_id: str) -> Path:
    if len(run_id) != 32 or any(c not in "0123456789abcdef" for c in run_id):
        raise ValueError("Invalid Timesheet Clerk job ID")
    return root / "jobs" / run_id / "status.json"


def write_status(root: Path, payload: dict) -> None:
    _atomic_write_json(job_path(root, payload["run_id"]), payload, root=root)
    _atomic_write_json(root / "planner-sync-status.json", payload, root=root)


def read_job(root: Path, run_id: str) -> dict:
    return json.loads(job_path(root, run_id).read_text(encoding="utf-8"))


def recover_jobs(root: Path) -> None:
    """A fresh container cannot still be running a worker from the previous container."""
    latest = root / "planner-sync-status.json"
    for path in (root / "jobs").glob("*/status.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
            if job.get("status") not in {"STARTING", "RUNNING"}:
                continue
            job.update(status="FAILED", finished_at=now(), message="Timesheet Clerk generation was interrupted by a service restart. Refresh to try again.")
            _atomic_write_json(path, job, root=root)
            if latest.exists() and json.loads(latest.read_text(encoding="utf-8")).get("run_id") == job["run_id"]:
                _atomic_write_json(latest, job, root=root)
        except (OSError, ValueError, KeyError):
            continue


def launch_job(root: Path, monday: str, sunday: str, *, rebuild: bool = False, manual: bool = False) -> dict:
    validate_week(monday, sunday)
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    lease = (root / ".planner.lock").open("a", encoding="utf-8")
    try:
        try:
            fcntl.flock(lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise StateConflict("A Timesheet Clerk generation is already running. Wait for it to finish.") from exc
        run_id = uuid.uuid4().hex
        payload = {"run_id": run_id, "status": "STARTING", "pid": None, "profile": PROFILE,
                   "week": {"monday": monday, "sunday": sunday}, "rebuild": bool(rebuild),
                   "manual": bool(manual), "started_at": now(), "message": "Starting Timesheet Clerk planner…"}
        write_status(root, payload)
        env = os.environ.copy()
        env["TIMESHEET_CLERK_STATE_DIR"] = str(root)
        args = [sys.executable, "-m", "timesheet_clerk.jobs", str(root), run_id, str(lease.fileno())]
        try:
            child = subprocess.Popen(args, cwd=APP_ROOT, env=env, pass_fds=(lease.fileno(),), start_new_session=True)
        except Exception as exc:
            payload.update(status="FAILED", finished_at=now(), message=f"Could not start Timesheet Clerk: {exc}")
            write_status(root, payload)
            raise
        return {**payload, "pid": child.pid}
    finally:
        # The child inherits the same open-file description and retains the lease.
        lease.close()


def live_sources(monday: str, sunday: str) -> list[dict]:
    from .clockify import ClockifyClient
    from .config import ClockifyConfig
    tz = ZoneInfo(os.getenv("TZ", "Europe/Amsterdam"))
    start = datetime.combine(date.fromisoformat(monday), time.min, tzinfo=tz).isoformat()
    end = datetime.combine(date.fromisoformat(sunday), time(23, 59, 59), tzinfo=tz).isoformat()
    return ClockifyClient(ClockifyConfig.from_env()).get_time_entries(start, end)


def _mapping_decisions(root: Path, run_id: str, work: dict) -> list[dict]:
    from .bootstrap import bootstrap
    from .runtime import read_config, runtime_skill_path
    home = bootstrap()
    if not os.getenv("TIMESHEET_CLERK_MODEL", "").strip():
        raise StateConflict("Configure the Timesheet Clerk model first, or use Import for manual review.")
    directory = job_path(root, run_id).parent
    repo = PlanRepository(root)
    request = {"run_id": run_id, "work_items": work["work_items"], "simplicate_context": work["simplicate_context"],
               "policy": read_config(), "instructions": runtime_skill_path().read_text(encoding="utf-8"),
               "feedback_events": repo.feedback(limit=200), "rules": repo.read_rules()}
    _atomic_write_json(directory / "request.json", request, root=root)
    env = os.environ.copy()
    env.update(HERMES_HOME=str(hermes_root()), TIMESHEET_CLERK_JOB_DIR=str(directory),
               PYTHONPATH=str(APP_ROOT),
               OPENAI_API_KEY=os.getenv("TIMESHEET_CLERK_MODEL_API_KEY", ""),
               OPENROUTER_API_KEY=os.getenv("TIMESHEET_CLERK_MODEL_API_KEY", ""))
    # The model process needs only its provider key, no booking credentials or connector token.
    for key in ("CLOCKIFY_API_KEY", "SIMPLICATE_API_KEY", "SIMPLICATE_API_SECRET", "TIMESHEET_CLERK_API_TOKEN", "TIMESHEET_CLERK_UI_PASSWORD"):
        env.pop(key, None)
    prompt = ("Prepare the Timesheet Clerk mapping decisions for this job. Call timesheet_mapping_work, "
              "then submit exactly one decision for each source_id using timesheet_mapping_submit. "
              "Use only the supplied Simplicate targets. For uncertainty use ASK. Do not book hours. "
              "Legacy instructions mentioning mapping_prepare/apply refer to the server's own workflow; "
              "your tools for this job are mapping_work and mapping_submit only.")
    # The pinned Hermes one-shot path discovers native plugin toolsets before validating them.
    env["HERMES_MAX_ITERATIONS"] = "12"
    command = [hermes_executable(), "-p", PROFILE, "--toolsets", "timesheet_clerk_planner", "-z", prompt]
    timeout = int(os.getenv("TIMESHEET_CLERK_PLANNER_TIMEOUT", "600"))
    with (directory / "planner.log").open("ab") as handle:
        child = subprocess.Popen(command, cwd=home, env=env, stdout=handle, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            code = child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
            raise StateConflict("Timesheet Clerk planner timed out. The existing plan was preserved.")
    if code:
        raise StateConflict(f"Timesheet Clerk planner failed (exit {code}). See this job's planner log.")
    try:
        response = json.loads((directory / "decisions.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StateConflict("The planner did not submit mapping decisions. The existing plan was preserved.") from exc
    if response.get("run_id") != run_id or not isinstance(response.get("decisions"), list):
        raise StateConflict("Planner response belongs to a different Timesheet Clerk job")
    from .planner_policy import enforce_policy
    return enforce_policy(response["decisions"], request["policy"])


def generate(root: Path, run_id: str, job: dict) -> dict:
    from .orchestration import apply_mapping_decisions, find_working_week, prepare_mapping_work
    repo = PlanRepository(root)
    monday, sunday = job["week"]["monday"], job["week"]["sunday"]
    sources = live_sources(monday, sunday)
    work = prepare_mapping_work(repo, sources, monday=monday, sunday=sunday, rebuild=job["rebuild"])
    if work["no_op"]:
        return {"no_op": True, "summary": work["summary"]}
    if job["manual"]:
        decisions = [{"source_id": item["source_id"], "tier": "ASK", "booking_mode": "direct",
                      "why_not_auto": "Imported for manual review.", "confidence": 0.0} for item in work["work_items"]]
    elif work["work_items"]:
        decisions = _mapping_decisions(root, run_id, work)
    else:
        decisions = []
    fresh_sources = live_sources(monday, sunday)
    from .sync import source_snapshots
    if source_snapshots(fresh_sources) != source_snapshots(sources):
        raise StateConflict("Clockify changed during generation. Refresh again; the existing plan was preserved.")
    with state_lock(root):
        current = find_working_week(repo, monday, sunday)
        current_id, current_rev = (current or {}).get("plan_id"), (current or {}).get("revision")
        if (current_id, current_rev) != (work["base_plan_id"], work["base_revision"]):
            raise StateConflict("The plan was edited during generation. Refresh again to preserve your changes.")
        result = apply_mapping_decisions(repo, fresh_sources, monday=monday, sunday=sunday, decisions=decisions,
                                         rebuild=job["rebuild"], simplicate_context=work["simplicate_context"])
    return {"no_op": False, "summary": result["summary"], "mode": result["mode"]}


def run_job(root: Path, run_id: str) -> int:
    job = read_job(root, run_id)
    job.update(status="RUNNING", pid=os.getpid(), message="Timesheet Clerk is preparing mapping proposals.")
    write_status(root, job)
    try:
        result = generate(root, run_id, deepcopy(job))
        job.update(status="SUCCEEDED", result=result, message="Timesheet Clerk plan is ready for review.")
    except Exception as exc:
        job.update(status="FAILED", message=str(exc))
    job["finished_at"] = now()
    write_status(root, job)
    return 0 if job["status"] == "SUCCEEDED" else 1


if __name__ == "__main__":
    # The inherited lock remains open until this process exits.
    raise SystemExit(run_job(Path(sys.argv[1]), sys.argv[2]))
