# Timesheet Clerk setup

The first implementation slice is read-only. Configure these environment variables for the HERMES process before testing the tools:

```text
CLOCKIFY_API_KEY
CLOCKIFY_WORKSPACE_ID
CLOCKIFY_USER_ID
SIMPLICATE_BASE_URL
SIMPLICATE_API_KEY
SIMPLICATE_API_SECRET
SIMPLICATE_EMPLOYEE_ID
```

Optional:

```text
CLOCKIFY_BASE_URL=https://api.clockify.me/api/v1
```

Then restart/reload HERMES as required by the installed plugin version and test:

- `timesheet_clockify_entries`
- `timesheet_simplicate_context`
- `timesheet_simplicate_assignments`
- `timesheet_simplicate_booked_hours`

No Simplicate write capability is exposed to the agent in this version.
