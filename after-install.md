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

Also configure a frontend password:

```text
TIMESHEET_CLERK_UI_PASSWORD
```

Optional:

```text
CLOCKIFY_BASE_URL=https://api.clockify.me/api/v1
HERMES_PROFILE_ENV=/home/hermes/.hermes/profiles/atlas/.env
```

## Shared state

0.4.0 defaults to agent-independent state:

```text
/home/hermes/.hermes/timesheet-clerk
```

Do not point normal operation back at `/home/hermes/.hermes/profiles/atlas/timesheet-clerk`. Existing Atlas-scoped state is migrated automatically when the shared directory does not yet exist.

An explicit `TIMESHEET_CLERK_STATE_DIR` override is still supported when needed.

## Validate the plugin

Confirm the runtime exposes at least:

- `timesheet_config_get`
- `timesheet_clockify_entries`
- `timesheet_simplicate_assignments`
- `timesheet_simplicate_booking_assignments`
- `timesheet_simplicate_booked_hours`
- `timesheet_plan_sync`
- `timesheet_plan_active`

Repeated planning runs should use `timesheet_plan_sync`, not create a brand-new plan for every run.

## Frontend

Normal deployment should use the dedicated Compose service and `frontend/managed_launcher.py`. That gives automatic startup/restart and enables the Configuration-page `Restart frontend` button.

See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for the Compose, Caddy, shared-volume and update notes.

Manual troubleshooting fallback:

```bash
cd /home/hermes/.hermes/plugins/timesheet-clerk
TIMESHEET_CLERK_UI_PASSWORD='<secret>' \
TIMESHEET_CLERK_STATE_DIR=/home/hermes/.hermes/timesheet-clerk \
python frontend/managed_launcher.py
```

## Runtime configuration

Use the frontend Configuration page for planner profile, contract hours, confidence thresholds, preferred valid hour type (`Senior Consultant` by default) and retention.

Use the SKILL page to edit the live runtime `SKILL.md`. Saving it writes outside Git and triggers `/reload-skills` for the configured planner profile.

Simplicate write execution is still intentionally disabled until the controlled write path is validated.
