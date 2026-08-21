# Implementation status

This document records implementation facts that are more concrete than the functional design. `DESIGN.md` remains the source of truth for intended behaviour.

## 0.1.0 foundation

Implemented on branch `build/plugin-foundation`:

- native HERMES plugin manifest and `register(ctx)` entry point;
- environment-based secret/config loading;
- normalized structured API errors with retry classification;
- Clockify REST reads for time entries, projects and clients;
- Simplicate REST reads for projects, services/tasks, hour types, assignments and booked hours;
- assignment normalization for agent-facing context;
- four read-only HERMES tools:
  - `timesheet_clockify_entries`
  - `timesheet_simplicate_context`
  - `timesheet_simplicate_assignments`
  - `timesheet_simplicate_booked_hours`
- first `timesheet-clerk` SKILL with assignment-first, autonomy and learning policy;
- no write capability exposed to HERMES.

## Required environment variables

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

## Next validation step

Install this branch/plugin in the actual HERMES environment and run read-only calls against both APIs. The live responses are needed to validate the normalized Simplicate assignment shape before building plan generation and before implementing either booking write path.

The assignment booking write method remains intentionally unimplemented until the real Simplicate behaviour is verified.
