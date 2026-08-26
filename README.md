# HERMES Timesheet Clerk

Human-in-the-loop timesheet planning and booking for HERMES Agent.

> Status: **0.6.3 deterministic planner.** Clockify/Simplicate reads, mapping-decision orchestration, source reconciliation, explicit ignored-entry handling, review UI, feedback, approvals, safe week rebuilds and explicit current-week generation are available. Simplicate writes remain deliberately disabled until the booking path is validated.

See [`docs/DESIGN.md`](docs/DESIGN.md), [`docs/IMPLEMENTATION.md`](docs/IMPLEMENTATION.md) and [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## Architecture

0.6 removed LLM-authored booking-plan payloads. HERMES receives an exact list of Clockify work items and returns mapping decisions only. Python owns plan IDs, week metadata, Clockify source truth, durations, coverage, revisioning, merge behaviour, human-review preservation and persistence.

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
validated complete plan revision
```

## 0.6.3 ignored entries

Ignored Clockify rows such as lunch or excluded travel still count toward source coverage, but they are intentionally not bookable to Simplicate.

HERMES may return `ignored=true` without `booking_mode`, `assignment` or `direct_mapping`. Python normalizes that decision to a structural non-bookable placeholder (`booking_mode=direct`, empty targets, `billable=false`). Plan validation therefore does not require project/service/hour-type IDs for ignored rows.

This avoids forcing the planner to invent fake Simplicate mappings merely to satisfy schema validation.

## 0.6.2 current-week generation

0.6.2 separates the plan currently open in the frontend from whether the current calendar week already has a working plan. A historical week may remain active for review without hiding `Generate current week` for a missing current week.

Current-week creation uses `rebuild=false`. If no working plan exists for that exact week, the deterministic core treats the run as CREATE and leaves historical plans untouched.

## 0.6.1 source reconciliation

Removed Clockify detection is based on live Clockify IDs versus actual plan coverage, not snapshot history alone.

- A one-source plan row whose Clockify source disappeared is removed deterministically during normal refresh.
- A legacy consolidated row whose complete source bundle disappeared is removed deterministically.
- If only part of a legacy consolidated bundle disappeared, Timesheet Clerk returns `requires_explicit_rebuild` instead of guessing.
- A normal refresh may never automatically retry as a rebuild.

## Safety

- Legacy arbitrary plan mutation/reset tools are removed from the HERMES tool surface.
- Rebuild is create-before-switch and requires explicit user intent.
- Failed rebuilds leave existing plan state untouched.
- Missing active pointers can be recovered from stored plans.
- Background planner jobs persist explicit STARTING/RUNNING/SUCCEEDED/FAILED state.
- Runtime SKILL state receives a mandatory versioned guard.
- CI runs compile + pytest on every push to `main` and pull request.

## Shared state

Default production state:

```text
/home/hermes/.hermes/timesheet-clerk
```

State is independent from the plugin checkout, so plans, approvals, receipts, feedback, rules and the live runtime skill survive code updates.

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

## Refresh

A normal refresh calls `timesheet_mapping_prepare(..., rebuild=false)`. If it returns `no_op=true`, no LLM mapping work is required. Otherwise HERMES maps exactly the returned work items and submits one decision per `source_id` to `timesheet_mapping_apply`.

Changed Clockify source facts are re-fetched by the plugin at apply time. Human-reviewed booking fields remain authoritative during incremental refreshes. Removed sources and ignored-source normalization are deterministic Python responsibilities.

## Safe rebuild

A rebuild uses the same two tools with `rebuild=true`, but only after explicit user intent. The existing plan is not deleted first. A complete replacement is built and validated before activation.

## Review UI

The Streamlit frontend provides week/day views, modal review/editing, skip/restore, duration reflow, assignment/direct mapping overrides, configuration, runtime SKILL editing, state inspection, approvals and booking preparation.

If the current calendar week has no working plan, `Generate current week` remains available even while an older week is open.

## Source integrity

Normalized Clockify rows are source truth. Actual plan coverage is checked against the live Clockify week, protecting reconciliation even when historic source snapshots are incomplete or stale.

## Updating

The canonical repository is `bramvrensen/Hermes-Timesheet-Clerk`.

During recovery or major-version development, the deterministic fallback remains a manual pull inside `hermes-agent` followed by restarting `hermes-agent` and `timesheet-clerk-ui`.

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

Simplicate write execution remains disabled. Booking will only be enabled from immutable approved snapshots through deterministic, idempotent write paths.
