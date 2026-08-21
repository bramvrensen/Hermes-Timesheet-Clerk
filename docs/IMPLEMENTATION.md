# Implementation status

This document records implementation facts that are more concrete than the functional design. `DESIGN.md` remains the source of truth for intended behaviour.

## 0.1.8 foundation

Implemented on `main`:

- native HERMES directory-plugin entrypoint through root `__init__.py` with `register(ctx)`;
- canonical `ctx.register_tool(...)` usage with toolset, full model-facing schema and JSON-string handlers;
- native HERMES plugin manifest and `requires_env` prerequisites for Clockify/Simplicate configuration;
- bundled Timesheet Clerk skill registered through `ctx.register_skill(...)`;
- plugin skill qualified name: `timesheet-clerk:timesheet-clerk`;
- environment-based secret/config loading;
- normalized structured API errors with retry classification;
- Clockify REST reads for time entries, projects and clients;
- Simplicate REST reads for active projects, services/tasks, hour types, planned assignments, candidate assignment records and booked hours;
- assignment normalization for agent-facing context;
- six read-only HERMES tools, including temporary diagnostics:
  - `timesheet_clockify_entries`
  - `timesheet_simplicate_context`
  - `timesheet_simplicate_assignments`
  - `timesheet_simplicate_available_assignments`
  - `timesheet_simplicate_debug_assignments`
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

### Simplicate assignments

Validated behaviour so far:

- assignment membership is represented by `employees[]`;
- blocked assignments are identified by `status.is_blocked`;
- project status label `tab_pclosed` identifies closed projects;
- dated assignments can be used as planning evidence when their date range overlaps the requested period;
- undated assignments must **not** be interpreted as proof that they are currently available booking targets.

The previous `available_assignments` interpretation is therefore provisional. Before implementing the manual assignment override list, the raw REST assignment shape must be validated against the live tenant and correlated with project/service/hour-type masterdata.

### Temporary assignment diagnostic

Version 0.1.8 exposes:

```text
timesheet_simplicate_debug_assignments
```

This tool returns a deliberately small and safe projection of up to ten raw employee assignment records. It includes candidate relationship fields and the raw key names, but excludes credentials and arbitrary unrelated fields.

It exists only to answer these questions against the live tenant:

- which field links an assignment to a project;
- which field links it to a project service/task;
- which field carries the hour type;
- whether customer/organization information is embedded or must be resolved through project masterdata;
- what `hours` represents in the raw assignment object;
- which status fields can be used to exclude obsolete assignment records.

The diagnostic tool must be removed again once normalization is proven.

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
- `timesheet_simplicate_assignments` successfully returns dated planning records that match the Simplicate planning view.

Not yet validated:

- reliable manual assignment override candidate selection;
- assignment → customer/project/service/hour-type normalization;
- assignment booking write semantics.

## Next validation step

Pull/reload v0.1.8 and invoke `timesheet_simplicate_debug_assignments` with `limit: 3`. Use the returned raw field shapes to correct normalization before changing assignment candidate filtering again.
