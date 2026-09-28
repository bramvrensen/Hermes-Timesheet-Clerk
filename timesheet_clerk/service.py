"""Supervise the private API and Streamlit; Docker supervises this process."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading

from .api import make_server
from .bootstrap import bootstrap
from .deployment import APP_ROOT
from .jobs import recover_jobs
from .storage import default_state_dir


def main() -> int:
    bootstrap()
    recover_jobs(default_state_dir())
    server = make_server(port=int(os.getenv("TIMESHEET_CLERK_API_PORT", "8502")))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    child = subprocess.Popen([sys.executable, str(APP_ROOT / "frontend/managed_launcher.py")], cwd=APP_ROOT, start_new_session=True)
    stopped = threading.Event()

    def stop(signum, frame):
        del signum, frame
        stopped.set()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while not stopped.wait(1):
            if child.poll() is not None or not worker.is_alive():
                return 1
        return 0
    finally:
        server.shutdown()
        server.server_close()
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()


if __name__ == "__main__":
    raise SystemExit(main())
