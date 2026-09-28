"""Authenticated control API for the optional Hermes connection. No booking API."""
from __future__ import annotations

import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from .jobs import launch_job, read_job
from .storage import PlanNotFound, PlanRepository, StateConflict, default_state_dir

VERSION = "2.0.0"


def make_server(host: str = "0.0.0.0", port: int = 8502, *, root: Path | None = None):
    state = Path(root) if root is not None else default_state_dir()
    token = os.environ.get("TIMESHEET_CLERK_API_TOKEN", "")
    if len(token) < 24:
        raise ValueError("Set a Timesheet Clerk API token of at least 24 characters")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            return  # Never log headers, body or the access token.

        def respond(self, code: int, payload: dict):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def authorized(self) -> bool:
            if not hmac.compare_digest(self.headers.get("Authorization", ""), f"Bearer {token}"):
                self.respond(401, {"success": False, "message": "Timesheet Clerk authentication required"})
                return False
            return True

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/healthz":
                self.respond(200, {"service": "Timesheet Clerk", "version": VERSION})
                return
            if not self.authorized():
                return
            try:
                if path == "/v1/status":
                    from .sync import plan_summary
                    repo = PlanRepository(state)
                    try:
                        summary = plan_summary(repo.get_active())
                    except PlanNotFound:
                        summary = None
                    status_path = state / "planner-sync-status.json"
                    job = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else None
                    self.respond(200, {"success": True, "data": {"service": "Timesheet Clerk", "version": VERSION,
                                  "summary": summary, "job": job, "review_url": os.getenv("TIMESHEET_CLERK_PUBLIC_URL", "")}})
                elif path.startswith("/v1/jobs/"):
                    self.respond(200, {"success": True, "data": read_job(state, path.removeprefix("/v1/jobs/"))})
                elif path == "/v1/plans":
                    self.respond(200, {"success": True, "data": PlanRepository(state).list_plans(limit=20)})
                else:
                    self.respond(404, {"success": False, "message": "Unknown Timesheet Clerk endpoint"})
            except (FileNotFoundError, ValueError):
                self.respond(404, {"success": False, "message": "Timesheet Clerk job not found"})
            except Exception:
                self.respond(500, {"success": False, "message": "Could not read Timesheet Clerk state"})

        def do_POST(self):
            if not self.authorized():
                return
            if urlsplit(self.path).path != "/v1/planner/jobs":
                self.respond(404, {"success": False, "message": "Unknown Timesheet Clerk endpoint"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > 16384:
                    raise ValueError("Invalid request size")
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict) or set(body) - {"monday", "sunday", "manual"}:
                    raise ValueError("Only monday, sunday and manual are accepted; rebuild and booking require the review UI")
                if not isinstance(body.get("manual", False), bool):
                    raise ValueError("manual must be a boolean")
                if not isinstance(body.get("monday"), str) or not isinstance(body.get("sunday"), str):
                    raise ValueError("monday and sunday must be calendar dates")
                job = launch_job(state, body["monday"], body["sunday"], manual=body.get("manual", False))
                self.respond(202, {"success": True, "data": job})
            except StateConflict as exc:
                self.respond(409, {"success": False, "message": str(exc)})
            except (ValueError, KeyError) as exc:
                self.respond(400, {"success": False, "message": str(exc)})
            except Exception:
                self.respond(500, {"success": False, "message": "Could not start Timesheet Clerk planning"})

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server
