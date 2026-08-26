import json
from pathlib import Path
from types import SimpleNamespace

from timesheet_clerk.update_lifecycle import build_update_handler


class FakeRepo:
    def __init__(self, root: Path):
        self.root = root


class FakeLegacyPlugin:
    def __init__(self, root: Path):
        self.PLUGIN_ROOT = root
        self._calls = []
        self.PlanRepository = lambda: FakeRepo(root / "state")

    def _safe(self, call):
        try:
            return json.dumps({"success": True, "data": call()})
        except Exception as exc:
            return json.dumps({"success": False, "message": str(exc)})

    def _git(self, *args, **kwargs):
        self._calls.append(args)
        if args == ("status", "--porcelain"):
            return SimpleNamespace(stdout="")
        if args == ("rev-parse", "HEAD"):
            return SimpleNamespace(stdout="abc123\n")
        if args == ("pull", "--ff-only"):
            return SimpleNamespace(returncode=0, stdout="Already up to date.\n", stderr="")
        raise AssertionError(args)


def test_update_handler_uses_bound_legacy_private_helpers(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "plugin.yaml").write_text("name: timesheet-clerk\nversion: 0.5.15\n", encoding="utf-8")
    plugin = FakeLegacyPlugin(tmp_path)

    handler = build_update_handler(plugin)
    payload = json.loads(handler({}))

    assert payload["success"] is True
    assert payload["data"]["version"] == "0.5.15"
    assert payload["data"]["updated"] is False
    assert payload["data"]["gateway_restart_scheduled"] is False
