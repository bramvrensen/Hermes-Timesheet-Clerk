"""The embedded Hermes process can read work and submit decisions only."""
from __future__ import annotations

import json
import os
from pathlib import Path


def _request():
    directory = Path(os.environ["TIMESHEET_CLERK_JOB_DIR"])
    return directory, json.loads((directory / "request.json").read_text(encoding="utf-8"))


def work(params, **kwargs):
    del params, kwargs
    _, request = _request()
    return json.dumps({"success": True, "data": request}, ensure_ascii=False)


def submit(params, **kwargs):
    del kwargs
    directory, request = _request()
    decisions = params.get("decisions")
    if not isinstance(decisions, list):
        return json.dumps({"success": False, "message": "decisions must be an array"})
    expected = {item["source_id"] for item in request["work_items"]}
    received = [row.get("source_id") for row in decisions if isinstance(row, dict)]
    if len(received) != len(decisions) or len(received) != len(set(received)) or set(received) != expected:
        return json.dumps({"success": False, "message": "Submit exactly one decision per supplied source_id"})
    from timesheet_clerk.storage import _atomic_write_json
    path = directory / "decisions.json"
    if path.exists():
        return json.dumps({"success": False, "message": "This job already has submitted decisions"})
    _atomic_write_json(path, {"run_id": request["run_id"], "decisions": decisions}, root=directory)
    return json.dumps({"success": True, "message": "Timesheet Clerk decisions submitted. Stop now."})


def register(ctx):
    ctx.register_tool(name="timesheet_mapping_work", toolset="timesheet_clerk_planner",
                      schema={"name": "timesheet_mapping_work", "description": "Read this job's work, context and policy.",
                              "parameters": {"type": "object", "properties": {}}}, handler=work)
    ctx.register_tool(name="timesheet_mapping_submit", toolset="timesheet_clerk_planner",
                      schema={"name": "timesheet_mapping_submit", "description": "Submit mapping decisions for this job only.",
                              "parameters": {"type": "object", "properties": {"decisions": {"type": "array", "items": {"type": "object"}}},
                                             "required": ["decisions"]}}, handler=submit)
