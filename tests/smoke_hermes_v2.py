"""Exercise the real pinned Hermes CLI with a local, fake model provider (no live APIs)."""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import time

from timesheet_clerk.jobs import _mapping_decisions, job_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hermes-bin", required=True)
    args = parser.parse_args()
    calls = []
    auxiliary = []
    decision = {"source_id": "c1", "tier": "PROPOSE", "confidence": 0.8, "booking_mode": "direct",
                "direct_mapping": {"project_id": "p1", "service_id": "s1", "hour_type_id": "h1"},
                "why": "Local test mapping"}
    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            body = json.dumps({"data": [{"id": "timesheet-clerk-test-model"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            tools = {tool["function"]["name"] for tool in request.get("tools", [])}
            calls.append(tools)
            messages = request.get("messages", [])
            if not tools:
                auxiliary.append({"path": self.path, "messages": str(messages)[:500]})
            submitted = any(m.get("role") == "tool" and "decisions submitted" in str(m.get("content", "")) for m in messages)
            worked = any(m.get("role") == "tool" and '"work_items"' in str(m.get("content", "")) for m in messages)
            message = {"role": "assistant", "content": "Timesheet Clerk decisions submitted." if submitted else None}
            if not tools:
                message["content"] = "Timesheet Clerk test"
            elif not submitted:
                name = "timesheet_mapping_submit" if worked else "timesheet_mapping_work"
                arguments = {"decisions": [decision]} if worked else {}
                message["tool_calls"] = [{"id": "call_submit" if worked else "call_work", "type": "function",
                                          "function": {"name": name, "arguments": json.dumps(arguments)}}]
            choice = {"index": 0, "message": message, "finish_reason": "stop" if submitted or not tools else "tool_calls"}
            completion = {"id": "chatcmpl-local", "object": "chat.completion", "created": int(time.time()),
                          "model": "timesheet-clerk-test-model", "choices": [choice],
                          "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}}
            if request.get("stream"):
                delta = {**message}
                if "tool_calls" in delta:
                    delta["tool_calls"][0]["index"] = 0
                completion.update(object="chat.completion.chunk", choices=[{"index": 0, "delta": delta, "finish_reason": choice["finish_reason"]}])
                body = ("data: " + json.dumps(completion) + "\n\ndata: [DONE]\n\n").encode()
            else:
                body = json.dumps(completion).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream" if request.get("stream") else "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=provider.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="timesheet-clerk-hermes-") as directory:
            root = Path(directory) / "state"
            os.environ.update(TIMESHEET_CLERK_MODE="standalone", TIMESHEET_CLERK_STATE_DIR=str(root),
                              TIMESHEET_CLERK_HERMES_ROOT=str(Path(directory) / "private-hermes"),
                              TIMESHEET_CLERK_HERMES_BIN=str(Path(args.hermes_bin).resolve()),
                              TIMESHEET_CLERK_MODEL="timesheet-clerk-test-model", TIMESHEET_CLERK_MODEL_API_KEY="local-test-only",
                              TIMESHEET_CLERK_MODEL_BASE_URL=f"http://127.0.0.1:{provider.server_port}/v1",
                              TIMESHEET_CLERK_PLANNER_TIMEOUT="90", HERMES_HOME=str(Path(directory) / "atlas-unused"))
            run_id = "a" * 32
            work = {"work_items": [{"source_id": "c1", "source": {"description": "Local test"}}],
                    "simplicate_context": {"projects": [{"id": "p1"}], "services": [{"id": "s1"}], "hour_types": [{"id": "h1"}]}}
            try:
                result = _mapping_decisions(root, run_id, work)
            except Exception:
                print("Model request tool surfaces:", calls)
                print("Auxiliary model calls:", auxiliary)
                log = job_path(root, run_id).with_name("planner.log")
                if log.exists(): print(log.read_text(errors="replace")[-16000:])
                raise
            assert result[0]["source_id"] == "c1", result
            assert len(calls) >= 2, calls
            expected = {"timesheet_mapping_work", "timesheet_mapping_submit"}
            assert all(names == expected for names in calls if names), calls
            assert not (Path(directory) / "atlas-unused").exists()
            print("Timesheet Clerk private Hermes profile: real CLI and local model tool round-trip passed.")
            if auxiliary: print("Hermes auxiliary model calls:", auxiliary)
    finally:
        provider.shutdown()
        provider.server_close()
        thread.join()


if __name__ == "__main__":
    main()
