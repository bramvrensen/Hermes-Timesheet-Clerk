# Implementation status

This document records implementation facts that are more concrete than the functional design. `DESIGN.md` remains the source of truth for intended behaviour.

## 0.1.3 foundation

Implemented on `main`:

- native HERMES plugin manifest and `register(ctx)` entry point;
- native HERMES `requires_env` prerequisites for Clockify/Simplicate configuration;
- bundled Timesheet Clerk skill registered through `ctx.register_skill(...)`;
- plugin skill qualified name: `timesheet-clerk:timesheet-clerk`;
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
- Timesheet Clerk SKILL with assignment-first, autonomy and learning policy;
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

## Skill discovery

The skill is bundled inside the plugin repository at:

```text
skills/timesheet-clerk/SKILL.md
```

The plugin registers it explicitly during `register(ctx)`. Hermes namespaces plugin skills, so the expected skill name is:

```text
timesheet-clerk:timesheet-clerk
```

It should be discoverable through the normal skill tooling after the updated plugin has been pulled/reloaded.

## Next validation step

Reload/update the plugin in the actual HERMES environment and verify:

1. `timesheet-clerk:timesheet-clerk` is visible/loadable;
2. `timesheet_clockify_entries` can read live Clockify data;
3. `timesheet_simplicate_assignments` can read live Simplicate planning;
4. normalized assignment shape matches the actual API response.

The assignment booking write method remains intentionally unimplemented until the real Simplicate behaviour is verified.
