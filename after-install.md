# Timesheet Clerk setup

## Integration keys

Configure through HERMES Keys / plugin installation:

```text
CLOCKIFY_API_KEY
CLOCKIFY_WORKSPACE_ID
CLOCKIFY_USER_ID
SIMPLICATE_BASE_URL
SIMPLICATE_API_KEY
SIMPLICATE_API_SECRET
SIMPLICATE_EMPLOYEE_ID
```

Also configure a frontend password when the standalone review UI is used:

```text
TIMESHEET_CLERK_UI_PASSWORD
```

Optional:

```text
CLOCKIFY_BASE_URL=https://api.clockify.me/api/v1
TIMESHEET_CLERK_STATE_DIR=/home/hermes/.hermes/timesheet-clerk
TIMESHEET_CLERK_REVISION_RETENTION=10
```

Do not hard-code `HERMES_PROFILE_ENV` to Atlas for normal operation. The frontend derives the configured `planner_profile` and reads that profile's `.env` only when integration values are not already present in its environment.

## Shared state

Timesheet Clerk uses agent-independent state:

```text
/home/hermes/.hermes/timesheet-clerk
```

Do not point normal operation back at `/home/hermes/.hermes/profiles/atlas/timesheet-clerk`. Existing Atlas-scoped state is migrated automatically when the shared directory does not yet exist.

The configured planner profile is automatically wired to this shared runtime SKILL through `skills.external_dirs`, so ATLAS, ATLAS-worker or a future planner can use the same Clerk state without copying it into a profile.

## Validate the plugin

A 0.4.4 runtime should expose at least:

```text
timesheet_config_get
timesheet_clockify_entries
timesheet_sync_probe
timesheet_source_rebaseline
timesheet_plan_sync
timesheet_plan_active
timesheet_plan_summary
timesheet_update
```

For a legacy week without per-source Clockify snapshots, the first probe may report `requires_rebaseline: true`. Use `timesheet_source_rebaseline` once for that same interval. A second unchanged probe must then report zero new, changed and missing sources.

## Frontend

Normal deployment uses the dedicated Compose service and `frontend/managed_launcher.py`. Prefer running that service as the Hermes runtime UID/GID (normally `1000:1000`) while sharing the same persistent `/home/hermes/.hermes` volume.

The frontend is a review surface, not the plugin updater. Its `Restart frontend` control is only for Streamlit/frontend code changes.

See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for Compose, Caddy, shared-state permissions, smoke tests and update lifecycle.

## Runtime configuration

Use the frontend Configuration page for planner profile, contract hours, confidence thresholds, preferred valid hour type (`Senior Consultant` by default) and retention.

Hour Type is a global Simplicate choice in the UI and is not filtered by selected customer/project/task. The preferred hour type is sorted first when it actually exists.

Use the SKILL page to edit the live runtime `SKILL.md`. Saving it writes outside Git and calls Hermes' real skill reload function in the configured planner-profile context, without an LLM completion.

## Updating after 0.4.4 is installed

Ask Hermes to update Timesheet Clerk so it can call:

```text
timesheet_update
```

That tool performs a fast-forward Git pull, runs compile/tests, preserves shared skill/profile wiring and schedules Hermes' supervised in-band gateway restart after the current turn. No Docker/container restart and no Streamlit dependency are required.

The one-time upgrade from 0.4.3 to 0.4.4 still needs the existing manual pull plus one Hermes gateway/container restart because 0.4.3 does not yet contain the updater tool.

Simplicate write execution is still intentionally disabled until the controlled write path is validated.
