# HERMES Timesheet Clerk

Human-in-the-loop timesheet planning and booking for HERMES Agent.

> Status: **0.4.3 planning/review architecture.** Live Clockify/Simplicate reads, cheap delta sync, runtime policy, editable runtime skill, modal review UI, feedback, approval snapshots and retention exist. Simplicate writes remain deliberately disabled until the booking path is validated.

See [`docs/DESIGN.md`](docs/DESIGN.md), [`docs/IMPLEMENTATION.md`](docs/IMPLEMENTATION.md) and [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## 0.4.3

- added `timesheet_sync_probe`: every repeated week refresh can compare Clockify source state with the active plan before loading expensive mapping context;
- a no-change probe stops the planner immediately without Simplicate, learning context, another Clockify fetch or the full active plan;
- probe output contains only new/changed/missing source deltas when work is required;
- added `timesheet_plan_summary` and deterministic summaries from `timesheet_plan_sync` so the LLM no longer recalculates counts/totals;
- Clockify source rows are treated as immutable bundles of ID, description, client, project, timestamps and duration;
- review/edit moved into a Streamlit modal so cascading customer/project/task/hour-type interactions no longer move the main list around;
- date navigation now selects the relevant stored week and feeds Day view;
- manual hour-type review receives a global fallback only when Simplicate exposes no scoped service/hour-type relation; fallback choices are never AUTO evidence;
- the live runtime SKILL receives the 0.4.3 fast-path/source-integrity guard non-destructively.

## Principles

- HERMES thinks about mapping only when source changes require it.
- Timesheet Clerk performs source comparison, arithmetic, state and summaries deterministically.
- Streamlit reviews explicit plan state; it does not invent mapping decisions.
- One open working plan exists per week. Repeated runs sync instead of creating revision noise.
- Human review is preserved across syncs.
- Runtime config and live `SKILL.md` are mutable state outside Git.
- Approved booking input is immutable.

## Shared state

Default runtime state is `/home/hermes/.hermes/timesheet-clerk`, independent of planner profile. The old Atlas-scoped location is migrated once when required.

## Core HERMES tools

```text
timesheet_config_get
timesheet_clockify_entries
timesheet_sync_probe
timesheet_simplicate_context
timesheet_simplicate_assignments
timesheet_simplicate_booking_assignments
timesheet_simplicate_booked_hours
timesheet_plan_create
timesheet_plan_sync
timesheet_plan_active
timesheet_plan_summary
timesheet_plan_list
timesheet_learning_context
```

### Fast refresh

For an existing week the normal path is:

```text
timesheet_sync_probe
        ↓
   changes?
   ├─ no  → return deterministic summary and stop
   └─ yes → map only new/changed Clockify rows
             ↓
          timesheet_plan_sync
```

The probe compares Clockify source IDs and represented source facts against the active plan and returns new, changed and missing records. This prevents a no-op refresh from dragging complete plan, Simplicate and learning context through many LLM turns.

## Source integrity

A normalized Clockify row is an immutable source bundle. Its source ID, description, client, project, start/end timestamps and duration stay together. Simplicate mapping changes the booking target only. The planner must not swap or merge unrelated source facts.

## Deterministic summaries

Counts and totals come from Timesheet Clerk code, not LLM arithmetic. `timesheet_sync_probe`, `timesheet_plan_sync` and `timesheet_plan_summary` expose authoritative summary fields including plan/revision/status, source sync time, hour totals, ignored/pending counts and source-delta counts.

## Review UI

The frontend provides persistent login, week/day views, date navigation, planned start/end times, modal entry review, skip/restore, duration reflow, assignment override, cascading direct mapping, editable runtime SKILL, state inspector, maintenance controls and version display.

Direct-mapping hour types prefer validated service relations. When the Simplicate tenant does not expose such a relation, the UI may show the global hour-type catalog explicitly for manual selection. Runtime `preferred_hour_type` remains only a preference among available choices.

## Deployment

Use the dedicated `timesheet-clerk-ui` Compose service with `frontend/managed_launcher.py`, sharing the persistent `/home/hermes/.hermes` volume. The Configuration-page restart button writes the managed restart marker; the launcher also reaps orphaned child processes.

## Required integration configuration

```text
CLOCKIFY_API_KEY
CLOCKIFY_WORKSPACE_ID
CLOCKIFY_USER_ID
SIMPLICATE_BASE_URL
SIMPLICATE_API_KEY
SIMPLICATE_API_SECRET
SIMPLICATE_EMPLOYEE_ID
TIMESHEET_CLERK_UI_PASSWORD
```

## Safety boundary

Simplicate write execution is still disabled. The next write milestone remains a controlled deterministic booking from an approved snapshot, followed by idempotent day/week batching.
