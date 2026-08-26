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


def test_upgrade_sync_prompt_repairs_coverage_before_mapping():
    upgraded = ui_sync._upgrade_sync_prompt("sync week")
    assert "unprocessed_count > 0" in upgraded
    assert "timesheet_source_rebaseline" in upgraded
    assert "Do NOT stop after coverage repair" in upgraded
    assert "map ONLY entries that were created" in upgraded
    assert "preserve all previously reviewed/mapped entries unchanged" in upgraded
    assert "timesheet_plan_sync" in upgraded
    assert "Never book hours to Simplicate" in upgraded


def test_upgrade_sync_prompt_processes_changed_existing_entries():
    upgraded = ui_sync._upgrade_sync_prompt("sync week")
    assert "source_delta.changed_entries" in upgraded
    assert "entries covering changed Clockify source IDs" in upgraded
    assert "canonical Clockify source facts" in upgraded
    assert "description" in upgraded
    assert "original duration" in upgraded


def test_upgrade_sync_prompt_forbids_destructive_recovery():
    upgraded = ui_sync._upgrade_sync_prompt("sync week")
    assert "DESTRUCTIVE RECOVERY IS FORBIDDEN" in upgraded
    assert "never delete/reset/recreate the week" in upgraded
    assert "never attempt Fresh Start" in upgraded
    assert "stop and report the exact tool error" in upgraded


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
    assert "map ONLY entries that were created" in sent_prompt
    assert "source_delta.changed_entries" in sent_prompt
    assert "DESTRUCTIVE RECOVERY IS FORBIDDEN" in sent_prompt
    assert "hermes" in calls[0][0][0]


def test_full_rebuild_launch_does_not_append_refresh_contract(monkeypatch, tmp_path):
    calls=[]
    class Child: pid=5678
    def fake_popen(args,**kwargs): calls.append((args,kwargs)); return Child()
    monkeypatch.setattr(ui_sync.subprocess,"Popen",fake_popen)

    result=ui_sync.launch_sync(root=tmp_path,profile="atlas",prompt="full rebuild",apply_refresh_contract=False)

    assert result["status"]=="running" and result["pid"]==5678
    sent_prompt=calls[0][0][-1]
    assert sent_prompt == "full rebuild"
    assert "IMPORTANT REFRESH CONTRACT" not in sent_prompt
