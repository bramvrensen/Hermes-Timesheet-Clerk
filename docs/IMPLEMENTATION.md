# Implementation status

This document records implementation facts that are more concrete than the functional design. `DESIGN.md` remains the source of truth for intended behaviour.

## 0.1.7 foundation

Implemented on `main`:

- native HERMES directory-plugin entrypoint through root `__init__.py` with `register(ctx)`;
- canonical `ctx.register_tool(...)` usage with toolset, full model-facing schema and JSON-string handlers;
- native HERMES plugin manifest and `requires_env` prerequisites for Clockify/Simplicate configuration;
- bundled Timesheet Clerk skill registered through `ctx.register_skill(...)`;
- plugin skill qualified name: `timesheet-clerk:timesheet-clerk`;
- environment-based secret/config loading;
- normalized structured API errors with retry classification;
- Clockify REST reads for time entries, projects and clients;
- Simplicate REST reads for active projects, services/tasks, hour types, planned assignments, available assignment candidates and booked hours;
- assignment normalization for agent-facing context;
- five read-only HERMES tools:
  - `timesheet_clockify_entries`
  - `timesheet_simplicate_context`
  - `timesheet_simplicate_assignments`
  - `timesheet_simplicate_available_assignments`
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

Native directory plugins are discovered from a root `__init__.py` containing `register(ctx)`. A manifest `entrypoint: plugin.py` is not sufficient for the installed Hermes version. The repository therefore keeps `plugin.py` as the implementation module and exposes its `register` function from root `__init__.py`.

### Simplicate assignments

The live assignment model follows the previously working Antigravity implementation:

- assignment membership is represented by `employees[]`, not a singular `employee`/`employee_id` field;
- blocked assignments are identified by `status.is_blocked`;
- project status label `tab_pclosed` identifies closed projects and those are excluded from active context.

A critical distinction is now explicit:

- **planned assignments** have both `start_date` and `end_date` and overlap the requested period;
- **available assignments** are non-blocked assignments linked to the employee that may be valid booking/override candidates. Undated assignments are included here but are not treated as evidence that the employee is planned on them for a specific day.

This separation matches Simplicate's documented Insights planning model: `api_project_assignments_facts` contains daily planning facts and excludes assignments without a start or end date. The normal REST API does not expose an equivalent employee/day planning-facts endpoint, so the REST client uses the dated assignment period as planning evidence while keeping undated candidates separate.

`timesheet_simplicate_assignments` returns only planned assignments. `timesheet_simplicate_available_assignments` is intended for override candidate lookup. `timesheet_simplicate_context` exposes both as `planned_assignments` and `available_assignments`; the legacy `assignments` field aliases the planned set.

### Simplicate booked hours

The proven API query format is retained internally:

```text
q[employee.id]=employee:<id>
q[start_date][ge]=YYYY-MM-DD 00:00:00
q[start_date][le]=YYYY-MM-DD 23:59:59
```

These prefixes and timestamp conventions must not leak into the SKILL or plan contract.

## Validation status

Validated in the live Hermes environment:

- plugin installs from GitHub;
- required Keys are enforced during installation;
- plugin passes `hermes plugins doctor`;
- plugin toolset is enabled globally;
- `timesheet_clockify_entries` successfully returns live Clockify entries;
- `timesheet_simplicate_assignments` can be dynamically discovered and invoked by ATLAS/Hermes.

## Next validation step

Pull/reload v0.1.7 and verify for a single day:

1. `timesheet_simplicate_assignments` no longer returns undated historical assignments;
2. `timesheet_simplicate_available_assignments` still exposes those undated records as possible manual override targets;
3. planned assignment fields contain enough project/task/hour-type context for planned-assignment-first matching;
4. `timesheet_simplicate_booked_hours` returns only the configured employee's booked hours for the requested inclusive date range.

The assignment booking write method remains intentionally unimplemented until the real Simplicate write semantics are verified.
