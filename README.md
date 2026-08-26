# HERMES Timesheet Clerk

Human-in-the-loop timesheet planning and booking for HERMES Agent.

> Status: **0.6.4 deterministic planner.** Clockify/Simplicate reads, decisions-only mapping orchestration, source reconciliation, review UI, deterministic day scheduling, feedback, approvals, safe week rebuilds and current-week generation are available. Simplicate writes remain deliberately disabled until the booking path is validated.

See [`docs/DESIGN.md`](docs/DESIGN.md), [`docs/IMPLEMENTATION.md`](docs/IMPLEMENTATION.md) and [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## Architecture

HERMES receives exact Clockify work items and returns mapping decisions only. Python owns plan identity, Clockify source truth, durations, week metadata, coverage, revisioning, merge behaviour, human-review preservation, scheduling and persistence.

```text
Clockify + existing Clerk state
            ↓
timesheet_mapping_prepare
            ↓
 exact mapping work_items
            ↓
        HERMES
   mapping decisions only
            ↓
timesheet_mapping_apply
            ↓
validated + scheduled plan revision
```

## 0.6.4 review and scheduling

0.6.4 centralizes the daily booking timeline in one Python scheduler.

For every day:

- ignored rows remain source-covered but do not participate in the booking timeline;
- non-billable/internal entries are scheduled before billable entries;
- the first non-ignored entry starts at 09:00;
- following entries are contiguous using `planned_duration_seconds`;
- the same reflow runs after CREATE/REFRESH and human review changes such as duration, skip, restore and mapping edits.

Clockify timestamps remain immutable source evidence. Planned start/end timestamps are separate booking state.

Restore is fail-safe. Restoring an ignored entry without a complete target reopens it as `ASK/PENDING`; it can no longer become an invalid resolved AUTO entry with an empty mapping.

The Streamlit duration +/- controls use callbacks so they no longer mutate a widget key after the number input has been instantiated.

### Unknown is not ignored

Unclassified time is never silently discarded. Blank descriptions and recognized placeholders such as `?`, `??`, `?? -- ??`, `unknown` and `onbekend` are forced back to non-ignored `ASK` state even if HERMES incorrectly proposes `ignored=true`.

Ignored is reserved for positively identified exclusions such as configured lunch/travel rules.

### UI loading performance

Simplicate review context previously loaded projects, services, hour types and booking assignments sequentially, making cold frontend loads roughly the sum of four API latencies.

0.6.4:

- fetches those independent Simplicate datasets concurrently;
- stores normalized review context in a persistent per-week Clerk cache for 30 minutes;
- keeps that cache across Streamlit/container restarts.

The first uncached load is therefore bounded roughly by the slowest Simplicate call instead of all four calls added together. Warm loads use local state/cache.

## 0.6.3 ignored entries

Ignored Clockify rows count toward source coverage but are intentionally not bookable. HERMES may omit booking target fields for `ignored=true`; Python normalizes the non-bookable state and plan validation does not require Simplicate target IDs.

## 0.6.2 current-week generation

A historical week can remain open while `Generate current week` is offered for a missing current calendar week. CREATE detection is based on the exact week, not the global active pointer.

## 0.6.1 source reconciliation

Removed Clockify sources are determined from live source IDs versus actual plan coverage. Safe single-source removals are reconciled automatically; ambiguous partial loss from a legacy consolidated row fails closed with `requires_explicit_rebuild`.

## Safety

- HERMES cannot submit arbitrary booking-plan JSON.
- Legacy destructive create/sync/rebaseline/fresh-start tools are removed from the planner surface.
- A normal refresh may never escalate itself into a rebuild.
- Rebuild is create-before-switch; failed rebuilds preserve existing state.
- Missing active pointers can be recovered from stored plans.
- Background planner jobs use explicit STARTING/RUNNING/SUCCEEDED/FAILED state.
- Runtime SKILL state receives a mandatory versioned planner guard.
- CI runs compile + pytest on pushes to `main` and pull requests.

## Shared state

Default production state:

```text
/home/hermes/.hermes/timesheet-clerk
```

Plans, approvals, receipts, feedback, rules, runtime SKILL state and UI context cache live outside the plugin checkout and survive code updates.

## Core HERMES tools

```text
timesheet_config_get
timesheet_clockify_entries
timesheet_sync_probe
timesheet_mapping_prepare
timesheet_mapping_apply
timesheet_simplicate_context
timesheet_simplicate_assignments
timesheet_simplicate_booking_assignments
timesheet_simplicate_available_assignments
timesheet_simplicate_booked_hours
timesheet_plan_active
timesheet_plan_summary
timesheet_plan_list
timesheet_learning_context
timesheet_update
```

## Updating

The canonical repository is `bramvrensen/Hermes-Timesheet-Clerk`.

During recovery/development the deterministic fallback is a Git fast-forward pull inside `hermes-agent`, followed by restarting `hermes-agent` and `timesheet-clerk-ui`.

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

## Booking boundary

Simplicate writes remain disabled. Booking will only execute from immutable approved snapshots through deterministic, idempotent write paths.
