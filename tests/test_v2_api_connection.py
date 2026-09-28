import importlib.util
import json
from pathlib import Path
import threading

import pytest
import requests

from timesheet_clerk import api
from timesheet_clerk.jobs import write_status

TOKEN = "test-timesheet-clerk-token-123456789"


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("TIMESHEET_CLERK_API_TOKEN", TOKEN)
    service = api.make_server("127.0.0.1", 0, root=tmp_path)
    thread = threading.Thread(target=service.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{service.server_port}", tmp_path
    service.shutdown()
    service.server_close()
    thread.join()


def test_api_health_and_required_auth(server):
    url, _ = server
    assert requests.get(url + "/healthz").json()["service"] == "Timesheet Clerk"
    assert requests.get(url + "/v1/status").status_code == 401
    assert requests.get(url + "/v1/status", headers={"Authorization": "Bearer wrong"}).status_code == 401
    result = requests.get(url + "/v1/status", headers={"Authorization": f"Bearer {TOKEN}"})
    assert result.status_code == 200 and result.json()["data"]["summary"] is None


def test_api_has_no_booking_or_rebuild_surface(server, monkeypatch):
    url, _ = server
    headers = {"Authorization": f"Bearer {TOKEN}"}
    monkeypatch.setattr(api, "launch_job", lambda *a, **k: pytest.fail("Must not launch"))
    assert requests.post(url + "/v1/book", headers=headers, json={}).status_code == 404
    assert requests.post(url + "/v1/planner/jobs", headers=headers, json={"monday": "2026-08-24", "sunday": "2026-08-30", "rebuild": True}).status_code == 400
    assert requests.get(url + "/v1/jobs/../../.env", headers=headers).status_code == 404


def test_authenticated_job_launch_and_persistent_status(server, monkeypatch):
    url, root = server
    run_id = "a" * 32
    calls = []
    def launch(root, monday, sunday, **kwargs):
        calls.append((monday, sunday, kwargs))
        job = {"run_id": run_id, "status": "RUNNING"}
        write_status(root, job)
        return job
    monkeypatch.setattr(api, "launch_job", launch)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    response = requests.post(url + "/v1/planner/jobs", headers=headers, json={"monday": "2026-08-24", "sunday": "2026-08-30"})
    assert response.status_code == 202
    assert calls == [("2026-08-24", "2026-08-30", {"manual": False})]
    assert requests.get(url + "/v1/jobs/" + run_id, headers=headers).json()["data"]["status"] == "RUNNING"


def test_connection_plugin_only_calls_service_and_registers_three_tools(server, monkeypatch):
    from hermes_plugins.connection import register, status, job
    url, root = server
    monkeypatch.setenv("TIMESHEET_CLERK_API_URL", url)
    monkeypatch.setenv("TIMESHEET_CLERK_API_TOKEN", TOKEN)
    assert json.loads(status({}))["data"]["service"] == "Timesheet Clerk"
    assert json.loads(job({"run_id": "../../.env"}))["success"] is False
    class Context:
        tools = []
        def register_tool(self, **kwargs): self.tools.append(kwargs)
        def register_skill(self, *args): pass
    ctx = Context()
    register(ctx)
    assert {t["name"] for t in ctx.tools} == {"timesheet_clerk_status", "timesheet_clerk_generate", "timesheet_clerk_job"}


def test_connection_installer_creates_dedicated_profile_and_preserves_default(server, tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("connection_installer", source / "connect-hermes.py")
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    home = tmp_path / "atlas"
    home.mkdir()
    (home / "config.yaml").write_text("model: original\n")
    (home / ".env").write_text("KEEP=private\n")
    def fetch(url):
        if "/commits/" in url: return json.dumps({"sha": "a" * 40}).encode()
        return (source / "hermes_plugins/connection" / url.rsplit("/", 1)[-1]).read_bytes()
    monkeypatch.setattr(installer, "fetch", fetch)
    commands = []
    def run(args, **kwargs):
        commands.append(args)
        if "create" in args:
            (home / "profiles/timesheet-clerk").mkdir(parents=True)
    monkeypatch.setattr(installer.subprocess, "run", run)
    own = installer.connect(home, "hermes", url=server[0], token=TOKEN, ref="feature/v2", yes=True)
    assert (home / "config.yaml").read_text() == "model: original\n"
    assert (home / ".env").read_text() == "KEEP=private\n"
    assert (own / "plugins/timesheet-clerk-connection/__init__.py").exists()
    assert "CLOCKIFY" not in (own / ".env").read_text()
    assert (own / ".env").stat().st_mode & 0o777 == 0o600
    assert ["hermes", "-p", "timesheet-clerk", "config", "set", "platform_toolsets.cli", '["timesheet_clerk"]'] in commands
