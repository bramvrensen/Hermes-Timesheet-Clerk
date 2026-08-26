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
        " IMPORTANT REFRESH CONTRACT: if timesheet_sync_probe reports source_delta.unprocessed_count > 0, "
        "first call timesheet_source_rebaseline for the same interval to deterministically restore plan coverage. "
        "Do NOT stop after coverage repair. Then call timesheet_plan_active and map ONLY entries that were created by "
        "that repair and remain unresolved ASK entries; preserve all previously reviewed/mapped entries unchanged. "
        "For those repaired ASK entries, load timesheet_config_get, timesheet_learning_context and only the Simplicate "
        "assignment/context data needed to apply the same AUTO/PROPOSE/ASK mapping policy used for initial plan generation. "
        "After mapping those repaired entries, call timesheet_plan_sync with the complete active plan, preserving canonical "
        "Clockify source IDs/snapshots and every existing human review value. Never book hours to Simplicate during refresh. "
        "If no repaired ASK entries require mapping, stop with the deterministic summary."
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
