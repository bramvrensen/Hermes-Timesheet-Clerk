import ast
from pathlib import Path

import timesheet_clerk.ui_sync as ui_sync


def test_ui_sync_does_not_import_provider_clients():
    source = Path(ui_sync.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules = set()
    imported_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import): imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported_modules.add(node.module or "")
            imported_names.update(alias.name for alias in node.names)
    assert not any(name.endswith("clockify") for name in imported_modules)
    assert not any(name.endswith("config") for name in imported_modules)
    assert "ClockifyClient" not in imported_names
    assert "ClockifyConfig" not in imported_names
    assert not any("simplicate" in name.lower() for name in imported_modules)


def test_upgrade_sync_prompt_repairs_unprocessed_coverage_without_plan_sync():
    upgraded = ui_sync._upgrade_sync_prompt("sync week")
    assert "unprocessed_count > 0" in upgraded
    assert "timesheet_source_rebaseline" in upgraded
    assert "do NOT construct or call timesheet_plan_sync" in upgraded
    assert "unresolved ASK entries" in upgraded


def test_launch_sync_only_starts_hermes(monkeypatch, tmp_path):
    calls=[]
    class Child: pid=1234
    def fake_popen(args,**kwargs): calls.append((args,kwargs)); return Child()
    monkeypatch.setattr(ui_sync.subprocess,"Popen",fake_popen)
    result=ui_sync.launch_sync(root=tmp_path,profile="atlas",prompt="sync week")
    assert result["status"]=="running" and result["pid"]==1234
    sent_prompt=calls[0][0][-1]
    assert sent_prompt.startswith("sync week")
    assert "timesheet_source_rebaseline" in sent_prompt
    assert "hermes" in calls[0][0][0]
