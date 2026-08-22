# Deployment guide

This document records the deployment details that were easy to get wrong while wiring the Timesheet Clerk frontend into the Hermes VPS.

## Shared state

Timesheet Clerk state is agent-independent in 0.4.x. Unless `TIMESHEET_CLERK_STATE_DIR` is explicitly set, the runtime uses:

```text
/home/hermes/.hermes/timesheet-clerk
```

This directory contains runtime configuration, the editable live `SKILL.md`, open plans, review revisions, feedback, learned rules, approval snapshots, receipts and frontend logs.

The old Atlas-scoped location:

```text
/home/hermes/.hermes/profiles/atlas/timesheet-clerk
```

is migrated once on startup when the shared directory does not yet exist. This means `planner_profile` can later change from `atlas` to `atlas-worker` without moving Clerk state.

An explicit override still wins:

```text
TIMESHEET_CLERK_STATE_DIR=/some/other/persistent/path
```

## Plugin checkout versus runtime state

Keep these separate:

```text
plugin code (Git managed)
/home/hermes/.hermes/plugins/timesheet-clerk

runtime state (not Git managed)
/home/hermes/.hermes/timesheet-clerk
```

The runtime `SKILL.md` is copied from the repository template on first use and then edited outside Git. Git pulls therefore cannot overwrite the live skill.

## Recommended Compose service

Do not run Streamlit manually for normal operation. Run it as its own Compose service so it starts after reboot and restarts after failures.

Use the same Hermes image/runtime and the same persistent Hermes data volume as the existing `hermes-agent` service. The exact image and volume names depend on the VPS Compose file, so reuse the values already present there instead of copying placeholders literally.

Example service:

```yaml
timesheet-clerk-ui:
  image: ${HERMES_IMAGE}
  restart: unless-stopped
  volumes:
    - hermes-data:/home/hermes/.hermes
  environment:
    TIMESHEET_CLERK_STATE_DIR: /home/hermes/.hermes/timesheet-clerk
    TIMESHEET_CLERK_PLUGIN_DIR: /home/hermes/.hermes/plugins/timesheet-clerk
    TIMESHEET_CLERK_UI_PASSWORD: ${TIMESHEET_CLERK_UI_PASSWORD}
    TIMESHEET_CLERK_UI_PORT: "8501"
    TIMESHEET_CLERK_UI_BASE_PATH: timesheet
    HERMES_PROFILE_ENV: /home/hermes/.hermes/profiles/atlas/.env
  entrypoint:
    - python
    - /home/hermes/.hermes/plugins/timesheet-clerk/frontend/managed_launcher.py
```

Notes:

- `restart: unless-stopped` makes the frontend survive host/container restarts.
- The entire `/home/hermes/.hermes` tree must be the same persistent volume the Hermes runtime uses. Otherwise the frontend sees a different plugin checkout/state tree.
- `HERMES_PROFILE_ENV` is currently only used to load missing integration environment values for standalone UI reads. Planner ownership itself is controlled by runtime config and can be changed to `atlas-worker`.
- The managed launcher watches `/home/hermes/.hermes/timesheet-clerk/frontend-restart.request`. The Configuration page writes this marker when `Restart frontend` is clicked.
- The launcher is PID 1 in the dedicated frontend container and explicitly reaps completed adopted child processes. This prevents background planner runs from accumulating as `<defunct>` zombie processes.
- With the Hermes image, use `entrypoint:` rather than `command:` for the launcher. The normal image entrypoint starts the Hermes gateway and otherwise creates a second Hermes runtime inside the UI container.

If the existing Compose stack does not expose an `${HERMES_IMAGE}` variable, replace it with the exact image already used by the current `hermes-agent` service.

## Caddy

Caddy should reverse proxy `/timesheet` to the Streamlit service. Keep Streamlit off the public internet directly.

When both Caddy and `timesheet-clerk-ui` are on the same Docker network, proxy to the service name and internal port, for example:

```caddyfile
handle_path /timesheet/* {
    reverse_proxy timesheet-clerk-ui:8501
}
```

If the existing Caddy setup uses a host-published port instead, proxy to that address. Do not publish Streamlit publicly unless the surrounding firewall/auth setup explicitly requires it.

The app itself is started with:

```text
--server.baseUrlPath timesheet
```

so the Caddy route and Streamlit base path must agree.

## Environment and secrets

Integration credentials remain Hermes/plugin secrets, not frontend source code. Required values are:

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

The standalone frontend loads missing Simplicate values from `HERMES_PROFILE_ENV`. Do not copy API secrets into the repository or runtime config JSON.

## Hermes profile cleanup

Warnings printed while invoking the Hermes CLI usually come from the live profile rather than this repository. Two examples seen during deployment were:

```text
Warning: Unknown toolsets: fetch-json, timesheet_clerk
```

and:

```text
Deprecated .env settings detected: TERMINAL_CWD=/opt/hermes
```

Treat these as profile-configuration issues:

1. inspect `/home/hermes/.hermes/profiles/<profile>/config.yaml` for configured toolsets;
2. compare those names with toolsets actually registered by the current Hermes/plugin runtime;
3. remove stale/renamed toolset entries instead of suppressing the warning;
4. move the deprecated `TERMINAL_CWD` value from `.env` into `config.yaml` as:

```yaml
terminal:
  cwd: /opt/hermes
```

5. remove `TERMINAL_CWD=...` from the profile `.env` only after `config.yaml` contains the replacement;
6. restart/reload the affected profile and confirm the warnings are gone.

Do not make these profile edits from the Timesheet Clerk Git repository. The profile is mutable deployment state.

## Updating the plugin

The dashboard and shell may point at different plugin clones if the deployment has been wired incorrectly. Before debugging a version mismatch, verify which checkout each runtime actually uses.

Canonical deployment target for 0.4.x is:

```text
/home/hermes/.hermes/plugins/timesheet-clerk
```

After a Git update:

1. verify `plugin.yaml` and `timesheet_clerk/__init__.py` show the same version;
2. reload Hermes skills/plugin registration as required by the dashboard/runtime;
3. use the frontend Configuration page `Restart frontend` button when the managed launcher is active.

Runtime state under `/home/hermes/.hermes/timesheet-clerk` is not touched by the Git update.

## Manual fallback

For troubleshooting only, the managed launcher can be run directly from the plugin checkout:

```bash
cd /home/hermes/.hermes/plugins/timesheet-clerk
TIMESHEET_CLERK_UI_PASSWORD='<secret>' \
TIMESHEET_CLERK_STATE_DIR=/home/hermes/.hermes/timesheet-clerk \
python frontend/managed_launcher.py
```

A manually started foreground process obviously does not survive a reboot. Compose is the intended steady-state deployment.
