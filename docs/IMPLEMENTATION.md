# Implementation status

This document records implementation facts that are more concrete than the functional design. `DESIGN.md` remains the source of truth for intended behaviour.

## 0.1.6 foundation

Implemented on `main`:

- native HERMES directory-plugin entrypoint through root `__init__.py` with `register(ctx)`;
- canonical `ctx.register_tool(...)` usage with toolset, full model-facing schema and JSON-string handlers;
- native HERMES plugin manifest and `requires_env` prerequisites for Clockify/Simplicate configuration;
- bundled Timesheet Clerk skill registered through `ctx.register_skill(...)`;
- plugin skill qualified name: `timesheet-clerk:timesheet-clerk`;
- environment-based secret/config loading;
- normalized structured API errors with retry classification;
- Clockify REST reads for time entries, projects and clients;
- Simplicate REST reads for active projects, services/tasks, hour types, relevant employee assignments and booked hours;
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

## Important compatibility findings

### Native Hermes plugin boundary

Native directory plugins are discovered from a root `__init__.py` containing `register(ctx)`. A manifest `entrypoint: plugin.py` is not sufficient for the installed Hermes version. The repository therefore keeps `plugin.py` as the implementation module and exposes its `register` function from root `__init__.py`.

### Simplicate assignments

The live assignment model follows the previously working Antigravity implementation:

- assignment membership is represented by `employees[]`, not a singular `employee`/`employee_id` field;
- relevant assignments must overlap the requested period;
- open-ended assignments have no end date;
- blocked assignments are identified by `status.is_blocked`;
- project status label `tab_pclosed` identifies closed projects and those are excluded from active context.

The client deliberately filters these transport quirks internally before returning normalized assignments.

### Simplicate booked hours

The proven API query format is retained internally:

```text
q[employee.id]=employee:<id>
q[start_date][ge]=YYYY-MM-DD 00:00:00
q[start_date][le]=YYYY-MM-DD 23:59:59
```

These prefixes and timestamp conventions must not leak into the SKILL or plan contract.

## Next validation step

Pull/reload v0.1.6 in the actual HERMES environment and verify:

1. `timesheet_simplicate_assignments` for a single day returns only assignments containing the configured employee, overlapping that day and not blocked;
2. the normalized assignment fields contain enough project/task/hour-type context for assignment-first matching;
3. `timesheet_simplicate_booked_hours` returns only the configured employee's booked hours for the requested inclusive date range.

The assignment booking write method remains intentionally unimplemented until the real Simplicate behaviour is verified.
