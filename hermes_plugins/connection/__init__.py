"""Optional Hermes client; no Timesheet Clerk state or integration secrets."""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlsplit
import requests


def _call(method, path, body=None):
    base = os.environ.get("TIMESHEET_CLERK_API_URL", "").rstrip("/")
    token = os.environ.get("TIMESHEET_CLERK_API_TOKEN", "")
    parsed = urlsplit(base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password or not token:
        return json.dumps({"success": False, "message": "Configure the Timesheet Clerk API address and connection token."})
    try:
        response = requests.request(method, base + path, headers={"Authorization": f"Bearer {token}"}, json=body, timeout=15, allow_redirects=False)
        if response.is_redirect:
            return json.dumps({"success": False, "message": "Use the direct Timesheet Clerk API address; redirects are refused."})
        payload = response.json()
        return json.dumps(payload, ensure_ascii=False)
    except (requests.RequestException, ValueError):
        return json.dumps({"success": False, "message": "Could not reach Timesheet Clerk. Check its address and connection."})


def status(params, **kwargs):
    return _call("GET", "/v1/status")


def generate(params, **kwargs):
    return _call("POST", "/v1/planner/jobs", {"monday": params.get("monday"), "sunday": params.get("sunday")})


def job(params, **kwargs):
    run_id = str(params.get("run_id") or "")
    if len(run_id) != 32 or any(c not in "0123456789abcdef" for c in run_id):
        return json.dumps({"success": False, "message": "Invalid Timesheet Clerk job ID"})
    return _call("GET", "/v1/jobs/" + run_id)


def register(ctx):
    ctx.register_skill("timesheet-clerk", Path(__file__).with_name("SKILL.md"), "Use the independent Timesheet Clerk application.")
    for name, description, handler, properties, required in (
        ("timesheet_clerk_status", "Read Timesheet Clerk status and review link.", status, {}, []),
        ("timesheet_clerk_generate", "Start Timesheet Clerk generation/refresh; no hours are booked.", generate,
         {"monday": {"type": "string"}, "sunday": {"type": "string"}}, ["monday", "sunday"]),
        ("timesheet_clerk_job", "Read a Timesheet Clerk background job.", job, {"run_id": {"type": "string"}}, ["run_id"]),
    ):
        ctx.register_tool(name=name, toolset="timesheet_clerk", description=description,
                          schema={"name": name, "description": description, "parameters": {"type": "object", "properties": properties, "required": required}}, handler=handler)
