# Implementation status

This document records implementation facts that are more concrete than the functional design. `DESIGN.md` remains the source of truth for intended behaviour.

## 0.1.4 foundation

Implemented on `main`:

- native HERMES directory-plugin entrypoint through root `__init__.py` with `register(ctx)`;
- canonical `ctx.register_tool(...)` usage with toolset, full model-facing schema and JSON-string handlers;
- native HERMES plugin manifest and `requires_env` prerequisites for Clockify/Simplicate configuration;
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

## Important compatibility finding

Native directory plugins are discovered from a root `__init__.py` containing `register(ctx)`. A manifest `entrypoint: plugin.py` is not sufficient for the installed Hermes version. The repository therefore keeps `plugin.py` as the implementation module and exposes its `register` function from root `__init__.py`.

## Next validation step

Pull/reload v0.1.4 in the actual HERMES environment and verify:

1. `timesheet-clerk:timesheet-clerk` is visible/loadable;
2. the four `timesheet_*` tools are registered;
3. `timesheet_clockify_entries` can read live Clockify data;
4. `timesheet_simplicate_assignments` can read live Simplicate planning;
5. normalized assignment shape matches the actual API response.

The assignment booking write method remains intentionally unimplemented until the real Simplicate behaviour is verified.
