# Implementation status

This document records implementation facts that are more concrete than the functional design. `DESIGN.md` remains the source of truth for intended behaviour.

## 0.1.10 foundation

Implemented on `main`:

- native HERMES directory-plugin entrypoint through root `__init__.py` with `register(ctx)`;
- canonical `ctx.register_tool(...)` usage with toolset, full model-facing schema and JSON-string handlers;
- native HERMES plugin manifest and `requires_env` prerequisites for Clockify/Simplicate configuration;
- bundled Timesheet Clerk skill stored under the Hermes productivity category convention at `skills/productivity/timesheet-clerk/SKILL.md` and registered through `ctx.register_skill(...)`;
- plugin skill qualified name remains `timesheet-clerk:timesheet-clerk` because Hermes namespaces plugin-bundled skills independently of their repository category path;
- environment-based secret/config loading;
- normalized structured API errors with retry classification;
- Clockify REST reads for time entries, projects and clients;
- Simplicate REST reads for active projects, services/tasks, hour types, planned assignments, validated booking assignment candidates and booked hours;
- assignment normalization based on the live tenant response;
- seven read-only HERMES tools, including temporary diagnostics and one compatibility alias:
  - `timesheet_clockify_entries`
  - `timesheet_simplicate_context`
  - `timesheet_simplicate_assignments`
  - `timesheet_simplicate_booking_assignments`
  - `timesheet_simplicate_available_assignments` (deprecated alias)
  - `timesheet_simplicate_debug_assignments` (temporary)
  - `timesheet_simplicate_booked_hours`
- Timesheet Clerk SKILL with planned-assignment-first, autonomy and learning policy;
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
skills/productivity/timesheet-clerk/SKILL.md
```

This matches Hermes' normal category layout (`skills/productivity/<skill>/SKILL.md`). Plugin-bundled skills are still registered through `ctx.register_skill(...)`, so Hermes qualifies the runtime name as:

```text
timesheet-clerk:timesheet-clerk
```

The category path improves repository consistency but does not by itself convert a plugin-bundled skill into a normal profile skill. If the dashboard/TUI skill inventory omits namespaced plugin skills, that is a Hermes presentation/discovery distinction rather than a missing file.

## Important compatibility findings

### Native Hermes plugin boundary

Native directory plugins are discovered from a root `__init__.py` containing `register(ctx)`. A manifest `entrypoint: plugin.py` is not sufficient for the installed Hermes version.

### Simplicate assignment shape validated in live tenant

The live REST response on 2026-08-21 established these concrete field locations:

```text
employees[]                  -> assigned employees
status.is_blocked            -> blocked state
status.is_done               -> completed state
is_planned                   -> explicit planning flag
project                      -> project object
project.organization         -> customer/organization
projectservice               -> task/service
projecthourstype             -> hour type
hours_type                   -> additional hour-type field present in the tenant response
hours                        -> assignment hours
hours_total                  -> total assignment hours
```

Normalized assignment output includes customer/project/task/hour-type context, dates, status, planning flags and a UI-friendly `Customer · Project · Assignment` display label.

### Planned assignments

`timesheet_simplicate_assignments` returns planning evidence only when all of these are true:

- configured employee is present in `employees[]`;
- assignment is not blocked or done;
- `is_planned = true`;
- both start and end dates exist;
- assignment overlaps the requested period.

### Booking assignments

`timesheet_simplicate_booking_assignments` returns credible assignment booking/override targets when all of these are true:

- configured employee is present in `employees[]`;
- assignment is not blocked or done;
- linked project is active;
- a project service exists;
- `projectservice.use_in_resource_planner = true`;
- if dated, the assignment overlaps the requested period.

An undated record may therefore be a booking candidate, but it is never treated as planning evidence by itself.

The old `timesheet_simplicate_available_assignments` name is retained temporarily as a compatibility alias and should not be used in new logic.

### Temporary assignment diagnostic

`timesheet_simplicate_debug_assignments` remains available temporarily so the normalization can be validated against live results. It should be removed after final validation.

### Simplicate booked hours

The proven API query format remains internal:

```text
q[employee.id]=employee:<id>
q[start_date][ge]=YYYY-MM-DD 00:00:00
q[start_date][le]=YYYY-MM-DD 23:59:59
```

## Validation status

Validated in the live Hermes environment:

- plugin installs from GitHub;
- required Keys are enforced during installation;
- plugin passes `hermes plugins doctor`;
- plugin toolset is enabled globally;
- `timesheet_clockify_entries` successfully returns live Clockify entries;
- `timesheet_simplicate_assignments` returns planning records matching the Simplicate planning view;
- `timesheet_simplicate_booking_assignments` returns a recognizable assignment list with customer/project/task context;
- raw assignment shape has been inspected directly from the live tenant.

Next validation targets:

- explain and remove the runtime difference between terminal/TUI tool discovery and WebUI chat tool discovery;
- validate hour-type labels/masterdata correlation;
- booked-hours reconciliation returns the expected employee/date subset;
- assignment booking write semantics remain intentionally unimplemented until verified.
