"""Background planner-sync status shared with the Streamlit frontend.

The frontend is deliberately transport-only: it never reads Clockify or Simplicate
credentials. Source probing, coverage repair and mapping belong to Timesheet Clerk
tools executed inside the Hermes plugin runtime.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _upgrade_sync_prompt(prompt: str) -> str:
    """Keep frontend refresh prompts aligned with the complete sync workflow."""
    prompt += (
        " IMPORTANT REFRESH CONTRACT: call timesheet_sync_probe first. If source_delta.unprocessed_count > 0, "
        "call timesheet_source_rebaseline for the same interval to restore plan coverage. Do NOT stop after coverage repair; "
        "continue with mapping in the same refresh run. Treat source_delta.changed_entries as mandatory refresh work: every changed "
        "Clockify source must be re-evaluated in this run, even when it is already covered by an existing plan entry. Call "
        "timesheet_plan_active and select mapping targets deterministically: entries covering IDs from source_delta.changed_entries, "
        "entries with mapping_state='PENDING' OR, for backward compatibility with pre-0.5.12 plans, ASK entries whose why_not_auto "
        "is exactly 'Clockify source ingested; Simplicate mapping still requires resolution.'. After coverage repair, map ONLY entries "
        "that were created by the coverage repair, entries covering changed Clockify source IDs, plus any already-existing PENDING or "
        "legacy-ingestion-sentinel entries. For all other entries, preserve all previously reviewed/mapped entries unchanged. Load "
        "timesheet_config_get, timesheet_learning_context and only the Simplicate context needed for those entries, then apply the same "
        "AUTO/PROPOSE/ASK policy used for initial generation. For changed existing entries, preserve prior human-reviewed mapping fields "
        "unless the changed Clockify facts invalidate them, but always pass the entry through timesheet_plan_sync so canonical Clockify "
        "source facts such as description, project, times and original duration are refreshed from the live source. After each pending "
        "target has been evaluated, set mapping_state='RESOLVED' even when the resulting tier remains ASK; replace the ingestion sentinel "
        "in why_not_auto with the actual mapping reason. Persist through timesheet_plan_sync using the complete active plan. Never book "
        "hours to Simplicate during refresh. DESTRUCTIVE RECOVERY IS FORBIDDEN: never delete/reset/recreate the week and never attempt "
        "Fresh Start as an error-recovery strategy. If sync fails, stop and report the exact tool error while preserving the current plan. "
        "IMPORTANT: pending mapping is independent from source_delta.has_changes. If the probe is a source no-op but the active plan still "
        "contains PENDING or legacy-ingestion-sentinel entries, map those entries before stopping."
    )
    return prompt


def launch_sync(*, root: Path, profile: str, prompt: str) -> dict[str, Any]:
    prompt = _upgrade_sync_prompt(prompt)
    log_dir = root / "logs"; log_dir.mkdir(parents=True, exist_ok=True)
    handle = (log_dir / "planner-refresh.log").open("ab")
    child = subprocess.Popen(
        ["/opt/hermes/.venv/bin/hermes", "-p", profile, "chat", "-q", prompt],
        cwd=f"/home/hermes/.hermes/profiles/{profile}", stdout=handle, stderr=subprocess.STDOUT, start_new_session=True,
    )
    payload={"pid":child.pid,"profile":profile,"started_at":datetime.now(timezone.utc).isoformat(),"status":"running","message":"Planner started; provider access remains inside Timesheet Clerk tools."}
    _write(root,payload); return payload


def sync_status(root: Path) -> dict[str, Any] | None:
    path=root/"planner-sync-status.json"
    if not path.is_file(): return None
    try: payload=json.loads(path.read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError): return None
    pid=int(payload.get("pid") or 0)
    if payload.get("status")=="running" and not _pid_running(pid):
        payload["status"]="finished"; payload["finished_at"]=datetime.now(timezone.utc).isoformat(); _write(root,payload)
    return payload


def clear_sync_status(root: Path) -> None:
    (root/"planner-sync-status.json").unlink(missing_ok=True)


def _pid_running(pid:int)->bool:
    if pid<=0:return False
    stat=Path(f"/proc/{pid}/stat")
    try:
        fields=stat.read_text(encoding="utf-8").split(); return len(fields)>2 and fields[2]!="Z"
    except OSError:
        try: os.kill(pid,0); return True
        except OSError:return False


def _write(root:Path,payload:dict[str,Any])->None:
    root.mkdir(parents=True,exist_ok=True); path=root/"planner-sync-status.json"; tmp=path.with_suffix(".tmp"); tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); os.replace(tmp,path)
