# Deployment guide

This document records the deployment details that were easy to get wrong while wiring Timesheet Clerk into the Hermes VPS.

## Shared state

Timesheet Clerk state is agent-independent. Unless `TIMESHEET_CLERK_STATE_DIR` is explicitly set, runtime state lives at:

```text
/home/hermes/.hermes/timesheet-clerk
```

The old Atlas-scoped location is migrated once when the shared directory does not yet exist. Changing `planner_profile` therefore does not move Clerk state.

The shared directory contains runtime configuration, the editable live `SKILL.md`, open plans, bounded working revisions, source snapshots, feedback, learned rules, approval snapshots, receipts and frontend logs.

### Ownership and permissions

Both Hermes agents and the optional Streamlit frontend may write this directory. 0.4.4 normalizes files/directories to the owner of the global Hermes state root and uses private group-safe modes:

```text
directories 0770
files       0660
```

The preferred Compose configuration also runs the frontend as the Hermes runtime UID/GID (`1000:1000` in the standard container). Code-level normalization remains as a safety net and the Configuration page exposes `Repair shared permissions` for existing mixed ownership.

Do not fix this by making state world-readable/writable.

## Plugin checkout versus runtime state

Keep Git-managed code and mutable state separate:

```text
plugin code
/home/hermes/.hermes/plugins/timesheet-clerk

runtime state
/home/hermes/.hermes/timesheet-clerk
```

The live runtime `SKILL.md` is copied from the repository template on first use and then edited outside Git. Git updates cannot overwrite it. Runtime guards are appended non-destructively when new versions require them.

## Planner profile and SKILL discovery

The shared runtime SKILL is registered through the configured planner profile's `skills.external_dirs`:

```yaml
skills:
  external_dirs:
    - /home/hermes/.hermes/timesheet-clerk
```

0.4.4 ensures this entry automatically when configuration is saved and when the plugin registers. This applies equally to `atlas`, `atlas-worker` or another future planner profile.

A SKILL save from the frontend invokes Hermes' real `reload_skills()` function in that profile's `HERMES_HOME`; it does not send `/reload-skills` as an LLM prompt.

## Recommended Compose service

Run Streamlit as its own Compose service so it starts after reboot and restarts after failures. Reuse the same Hermes image and persistent Hermes volume as the existing `hermes-agent` service.

```yaml
timesheet-clerk-ui:
  image: ${HERMES_IMAGE}
  user: "1000:1000"
  restart: unless-stopped
  volumes:
    - hermes-data:/home/hermes/.hermes
  environment:
    TIMESHEET_CLERK_STATE_DIR: /home/hermes/.hermes/timesheet-clerk
    TIMESHEET_CLERK_PLUGIN_DIR: /home/hermes/.hermes/plugins/timesheet-clerk
    TIMESHEET_CLERK_UI_PASSWORD: ${TIMESHEET_CLERK_UI_PASSWORD}
    TIMESHEET_CLERK_UI_PORT: "8501"
    TIMESHEET_CLERK_UI_BASE_PATH: timesheet
  entrypoint:
    - python
    - /home/hermes/.hermes/plugins/timesheet-clerk/frontend/managed_launcher.py
```

Notes:

- `user: "1000:1000"` keeps frontend writes aligned with the Hermes runtime identity. If a deployment uses another Hermes UID/GID, use that identity instead.
- The entire `/home/hermes/.hermes` tree must be the same persistent volume the Hermes runtime uses.
- Do not hard-code `HERMES_PROFILE_ENV` for Atlas. The UI derives the configured planner profile from Timesheet Clerk runtime config and uses that profile's `.env` only when integration values are not already in the environment.
- The managed launcher watches `/home/hermes/.hermes/timesheet-clerk/frontend-restart.request` and reaps adopted child processes.
- Use `entrypoint:` rather than `command:` with the Hermes image so the UI container does not start a second Hermes gateway.

## Caddy

Caddy should reverse proxy `/timesheet` to the Streamlit service. Keep Streamlit off the public internet directly.

```caddyfile
handle_path /timesheet/* {
    reverse_proxy timesheet-clerk-ui:8501
}
```

The app starts Streamlit with `--server.baseUrlPath timesheet`, so the proxy route and Streamlit base path must agree.

## Environment and secrets

Required values are:

```text
CLOCKIFY_API_KEY
CLOCKIFY_WORKSPACE_ID
CLOCKIFY_USER_ID
SIMPLICATE_BASE_URL
SIMPLICATE_API_KEY
SIMPLICATE_API_SECRET
SIMPLICATE_EMPLOYEE_ID
TIMESHEET_CLERK_UI_PASSWORD
```

Do not copy API secrets into Git or Timesheet Clerk runtime config JSON.

## Canonical test command

Do not use plain `pytest` from the repository root in the Hermes container. The checkout directory contains a hyphen and the plugin root package can confuse collection/import mode. The canonical smoke test is:

```bash
cd /home/hermes/.hermes/plugins/timesheet-clerk
PYTHONPATH=. uv run --with pytest pytest \
  --rootdir=tests \
  --import-mode=importlib \
  -q tests
```

This temporarily supplies pytest through `uv` and does not install it permanently into the Hermes venv.

## Updating the plugin

### Normal path from 0.4.4 onward

Use Hermes itself, not the frontend and not Docker:

```text
"Update Timesheet Clerk"
        ↓
timesheet_update
```

`timesheet_update` performs these steps against the fixed plugin checkout:

1. refuses to overwrite a dirty Git working tree;
2. performs `git pull --ff-only`;
3. ensures the shared runtime SKILL and configured planner-profile discovery remain wired;
4. schedules Hermes' supported in-band gateway restart after the current turn;
5. the supervisor respawns the gateway and the fresh process loads the new Python plugin module/tool registry.

Runtime state is untouched. The Streamlit frontend is not involved.

### Why a gateway restart is still required

A Git pull updates Python files on disk, but a running gateway keeps the already-imported plugin module and tool handlers in memory. A new session or `/reset` does not reload that module.

Hermes' `PluginManager.discover_and_load(force=True)` exists internally, but as of this deployment Hermes does not expose a stable running-gateway CLI/IPC command for safe Python plugin hot reload. Upstream feature requests for plugin reload are still open. 0.4.4 therefore uses Hermes' own supervised in-band gateway restart (`SIGUSR1` restart lifecycle), not a Docker/container restart.

This distinction matters:

```text
Git pull          = update code on disk
plugin reload     = reload Python/tool registrations (currently via gateway respawn)
SKILL reload      = rescan skill instructions only
frontend restart  = restart Streamlit only
```

A frontend restart is needed only when frontend code changed. The frontend is not the plugin updater.

## First upgrade to 0.4.4

0.4.3 does not yet contain `timesheet_update`, so the one-time upgrade to 0.4.4 still requires the existing deployment path: pull the repository, run the canonical tests, then restart the Hermes gateway/container once so 0.4.4's new tool registration is loaded. After that, future updates should use `timesheet_update`.

If the existing frontend service still runs as root, either recreate it with `user: "1000:1000"` or use `Repair shared permissions` after the first 0.4.4 start. The code also repairs mixed ownership when a privileged frontend process opens the shared repository.

## Clockify source baseline migration

Legacy plans created before 0.4.4 do not contain trustworthy per-Clockify source snapshots. `timesheet_sync_probe` therefore returns:

```text
requires_rebaseline: true
```

This is not a Clockify change. Call `timesheet_source_rebaseline` for the same interval. It stores a canonical source snapshot keyed by Clockify ID without changing human review values. An immediate second probe must return `new=0`, `changed=0`, `missing=0` unless Clockify genuinely changed.

## Working revision retention

Human review edits still create explicit working revisions for optimistic locking and auditability, but mutable history is bounded (10 revisions by default, overridable with `TIMESHEET_CLERK_REVISION_RETENTION`). Approval snapshots and feedback are stored separately and are not pruned by working-history compaction.

The Configuration page also exposes `Compact working revisions` for existing large histories.

## Hermes toolset warning

Hermes may emit:

```text
Warning: Unknown toolsets: fetch-json, timesheet_clerk
```

while initializing, even when both plugin toolsets subsequently register and are callable. We verified `timesheet_plan_active` and other Timesheet Clerk tools work after this warning. This currently behaves as an upstream plugin load-order/early-validation warning.

Do **not** remove a valid `timesheet_clerk` toolset from platform configuration merely to silence it. Treat the warning as non-blocking unless the tools are actually absent after startup.

The unrelated deprecated `TERMINAL_CWD` warning should be fixed by moving the value into profile `config.yaml`:

```yaml
terminal:
  cwd: /opt/hermes
```

and removing `TERMINAL_CWD` from `.env` afterward.

## Manual frontend fallback

For troubleshooting only:

```bash
cd /home/hermes/.hermes/plugins/timesheet-clerk
TIMESHEET_CLERK_UI_PASSWORD='<secret>' \
TIMESHEET_CLERK_STATE_DIR=/home/hermes/.hermes/timesheet-clerk \
python frontend/managed_launcher.py
```

A manually started foreground process does not survive reboot. Compose is the intended steady state.
