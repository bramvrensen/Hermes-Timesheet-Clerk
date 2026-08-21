# Implementation status

This document records implementation facts that are more concrete than the functional design. `DESIGN.md` remains the source of truth for intended behaviour.

## 0.1.9 foundation

Implemented on `main`:

- native HERMES directory-plugin entrypoint through root `__init__.py` with `register(ctx)`;
- canonical `ctx.register_tool(...)` usage with toolset, full model-facing schema and JSON-string handlers;
- native HERMES plugin manifest and `requires_env` prerequisites for Clockify/Simplicate configuration;
- bundled Timesheet Clerk skill registered through `ctx.register_skill(...)`;
- plugin skill qualified name: `timesheet-clerk:timesheet-clerk`;
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
skills/timesheet-clerk/SKILL.md
```

The plugin registers it explicitly during `register(ctx)`. Hermes namespaces plugin skills, so the expected skill name is:

```text
timesheet-clerk:timesheet-clerk
```

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

The earlier normalizer incorrectly expected customer/hour-type fields at the assignment root. Version 0.1.9 normalizes from the tenant-validated nested fields.

Normalized assignment output now includes:

- customer ID/name from `project.organization`;
- project ID/name/number;
- task/service ID/name and `use_in_resource_planner`;
- hour-type ID/name from `projecthourstype`, falling back to `hours_type`;
- assignment dates and hour values;
- explicit `is_planned`;
- normalized status;
- a UI-friendly `Customer · Project · Assignment` display label.

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

`timesheet_simplicate_debug_assignments` remains available temporarily so the new normalization can be validated against live results. It should be removed once the new booking-assignment output is confirmed.

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
- raw assignment shape has been inspected directly from the live tenant.

Next validation targets:

- `timesheet_simplicate_booking_assignments` returns a recognizable override list with customer/project/task/hour-type context;
- normalized hour type from `projecthourstype` matches Simplicate;
- booked-hours reconciliation returns the expected employee/date subset;
- assignment booking write semantics remain intentionally unimplemented until verified.
