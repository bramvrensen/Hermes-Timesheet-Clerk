# Timesheet Clerk setup

## Integration keys

Configure these through HERMES Keys / plugin installation:

```text
CLOCKIFY_API_KEY
CLOCKIFY_WORKSPACE_ID
CLOCKIFY_USER_ID
SIMPLICATE_BASE_URL
SIMPLICATE_API_KEY
SIMPLICATE_API_SECRET
SIMPLICATE_EMPLOYEE_ID
```

Optional integration setting:

```text
CLOCKIFY_BASE_URL=https://api.clockify.me/api/v1
```

Reload/restart HERMES after installing or updating the plugin.

## 0.2.0 validation

First confirm the integration tools:

- `timesheet_clockify_entries`
- `timesheet_simplicate_assignments`
- `timesheet_simplicate_booking_assignments`
- `timesheet_simplicate_booked_hours`

Then ask HERMES to prepare a real weekly Timesheet Clerk plan. The skill should gather context/evidence and persist a new revision-1 plan with `timesheet_plan_create`.

Confirm it exists with:

- `timesheet_plan_active`
- `timesheet_plan_list`

## Streamlit

Mutable plan/feedback state defaults to:

```text
$HERMES_HOME/timesheet-clerk
```

Set `TIMESHEET_CLERK_STATE_DIR` only when a different persistent path is required.

Set a frontend password and start Streamlit from the installed plugin/repository directory:

```bash
export TIMESHEET_CLERK_UI_PASSWORD='choose-a-password'
streamlit run frontend/app.py --server.address 127.0.0.1 --server.port 8501
```

Keep Streamlit on localhost and expose it through the intended `/timesheet` Caddy route/login setup.

The 0.2.0 UI supports review, corrections, feedback and immutable approval snapshots. **Simplicate writes are still intentionally disabled.**
