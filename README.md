# HERMES Timesheet Clerk

Human-in-the-loop timesheet planning and booking for HERMES Agent.

> Status: **0.4.4 planning/review architecture.** Live Clockify/Simplicate reads, cheap deterministic delta sync, immutable source snapshots, runtime policy, editable runtime skill, modal review UI, bounded working revisions, feedback, approval snapshots and retention exist. Simplicate writes remain deliberately disabled until the booking path is validated.

See [`docs/DESIGN.md`](docs/DESIGN.md), [`docs/IMPLEMENTATION.md`](docs/IMPLEMENTATION.md) and [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## 0.4.4

- Clockify delta detection now compares immutable per-source snapshots keyed by Clockify ID instead of aggregate booking rows;
- legacy plans without trustworthy source snapshots report `requires_rebaseline` instead of false `changed` results;
- `timesheet_source_rebaseline` establishes a fresh source baseline without changing human review decisions;
- `timesheet_plan_sync` refreshes canonical Clockify snapshots after a real sync;
- shared state ownership/permissions are normalized across Hermes agents and the optional frontend, with repair tooling for historic mixed ownership;
- runtime SKILL discovery follows the configured planner profile automatically via `skills.external_dirs`;
- SKILL saves call Hermes' real `reload_skills()` path in the correct profile context, with no LLM completion;
- Hour Type in the review UI shows the full Simplicate hour-type catalog independently from customer/project/task filters and prefers the configured `Senior Consultant` label when present;
- partial duration/restore edits no longer falsely mark unresolved direct entries as corrected;
- mutable working revision history is bounded while approvals/feedback remain durable;
- `timesheet_update` provides a Hermes-native update path: fast-forward Git pull followed by Hermes' supported supervised in-band gateway restart, without Docker/container restart or frontend dependency;
- deployment docs now distinguish code pull, plugin reload/restart, SKILL reload and frontend restart and include the canonical pytest smoke-test command.

## Principles

- HERMES thinks about mapping only when source changes require it.
- Timesheet Clerk performs source comparison, arithmetic, state and summaries deterministically.
- Streamlit reviews explicit plan state; it does not invent mapping decisions.
- One open working plan exists per week. Repeated planner syncs update it instead of producing sync revision noise.
- Human review is preserved across syncs and source re-baselines.
- Runtime config and live `SKILL.md` are mutable state outside Git.
- Approved booking input is immutable.
- Shared state is agent-independent: ATLAS, ATLAS-worker and future agents use the same Clerk state and runtime skill.

## Shared state

Default runtime state is:

```text
/home/hermes/.hermes/timesheet-clerk
```

This location is independent of planner profile. The old Atlas-scoped location is migrated once when required.

## Core HERMES tools

```text
timesheet_config_get
timesheet_clockify_entries
timesheet_sync_probe
timesheet_source_rebaseline
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
timesheet_update
```

## Cheap refresh path

```text
timesheet_sync_probe
        ↓
 baseline valid?
 ├─ no  → timesheet_source_rebaseline → probe again
 └─ yes
        ↓
   changes?
   ├─ no  → return deterministic summary and stop
   └─ yes → map only new/changed Clockify rows
             ↓
          timesheet_plan_sync
```

A no-op refresh must not load Simplicate, learning context or the full plan. The source baseline is per Clockify ID, so a booking entry that aggregates multiple Clockify rows does not create false changes.

## Source integrity

A normalized Clockify row is an immutable source bundle. Its ID, description, client, project, start/end timestamps and duration stay together in `clockify_source_snapshots`. Simplicate mapping, planned duration, ignored state and human review may change booking decisions but never source truth.

## Deterministic summaries

Counts and totals come from Timesheet Clerk code, not LLM arithmetic. `timesheet_sync_probe`, `timesheet_plan_sync` and `timesheet_plan_summary` expose authoritative summary fields including plan/revision/status, source sync time, hour totals, ignored/pending counts and source-delta counts.

## Review UI

The frontend provides persistent login, week/day views, date navigation, planned start/end times, modal entry review, skip/restore, duration reflow, assignment override, cascading customer/project/task mapping, a global Hour Type selector, editable runtime SKILL, state inspector, maintenance controls and version display.

`preferred_hour_type` defaults to `Senior Consultant`. It only changes ordering/preference among actual Simplicate hour types; it never invents a missing value.

## Updating

Normal future update path from Hermes:

```text
ask Hermes to update Timesheet Clerk
        ↓
timesheet_update
        ↓
git pull --ff-only
        ↓
shared skill/profile wiring preserved
        ↓
Hermes supervised gateway restart after current turn
        ↓
fresh session uses new plugin code/tools
```

This does not depend on Streamlit and does not restart the Docker container. Hermes upstream currently has no stable IPC/CLI endpoint for in-process Python plugin hot reload, so 0.4.4 uses Hermes' supported in-band gateway restart instead.

Frontend restart is separate and only required when Streamlit code changed.

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

Simplicate write execution is still disabled. The next write milestone remains controlled deterministic booking from an approved snapshot, followed by idempotent day/week batching.
