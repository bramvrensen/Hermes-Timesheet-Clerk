# HERMES Timesheet Clerk

Human-in-the-loop timesheet planning and booking for HERMES Agent.

> Status: **0.6.0 architecture cleanup.** Clockify/Simplicate reads, deterministic source comparison, mapping-decision orchestration, review UI, feedback, approvals and safe week rebuilds are available. Simplicate writes remain deliberately disabled until the booking path is validated.

See [`docs/DESIGN.md`](docs/DESIGN.md), [`docs/IMPLEMENTATION.md`](docs/IMPLEMENTATION.md) and [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## 0.6.0 architecture

0.6 removes LLM-authored booking-plan payloads. HERMES receives an exact list of Clockify work items and returns mapping decisions only. Python owns plan IDs, week metadata, Clockify source truth, durations, coverage, revisioning, merge behaviour, human-review preservation and persistence.

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

The planner no longer receives tools that can create/sync arbitrary plan JSON, rebaseline state or destructively reset a week.

## Safety changes in 0.6

- `timesheet_plan_create`, `timesheet_plan_sync`, `timesheet_source_rebaseline` and `timesheet_plan_fresh_start` are removed from the HERMES tool surface.
- Legacy destructive `fresh_start_week()` is disabled in code.
- Rebuild is create-before-switch: the existing plan remains available until a complete replacement has been built and validated.
- Failed rebuilds leave existing plan state untouched.
- Missing `active_plan.json` is repaired from the stored plan catalog instead of being interpreted as an empty repository.
- Background planner jobs persist `STARTING/RUNNING/SUCCEEDED/FAILED` state and an exit code. A vanished runner becomes `FAILED`, never an eternal `RUNNING` state.
- Runtime `SKILL.md` is migrated with a mandatory 0.6 guard because the live skill intentionally lives outside Git.
- CI runs compile + pytest on every push to `main` as well as pull requests.

## Shared state

Default production state:

```text
/home/hermes/.hermes/timesheet-clerk
```

State is independent from the planner profile and lives outside the plugin checkout. Plans, approvals, receipts, feedback, rules and the live runtime skill therefore survive plugin code updates.

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

A normal refresh calls `timesheet_mapping_prepare(..., rebuild=false)`. If it returns `no_op=true`, no LLM mapping work is required. Otherwise HERMES maps exactly the returned work items and submits exactly one decision per `source_id` to `timesheet_mapping_apply`.

Changed Clockify source facts are re-fetched by the plugin at apply time. The LLM never copies Clockify titles, timestamps or durations into persisted state.

Human-reviewed booking fields remain authoritative during incremental refreshes.

## Safe rebuild

A rebuild uses the same two tools with `rebuild=true`. The old plan is not deleted first. The plugin builds a complete replacement, validates Clockify coverage and the plan contract, writes the new plan, activates it and then best-effort marks the old working plan `SUPERSEDED`.

A tool failure before successful creation leaves the old plan available.

## Review UI

The Streamlit frontend provides week/day views, modal review/editing, skip/restore, duration reflow, assignment/direct mapping overrides, configuration, runtime SKILL editing, state inspection, approvals and booking preparation.

If the active pointer is missing but stored plans exist, the UI repairs the pointer and opens the newest stored plan. Configuration, SKILL and State remain accessible even when no plan exists.

Planner status is shown in the frontend as a real job state rather than inferred only from a PID.

## Source integrity

A normalized Clockify row is source truth. Source comparison tracks ID, description, client, project, tags, start/end timestamps and duration. Simplicate mapping, planned duration, ignore/review state and booking state do not redefine the source.

## Updating

The canonical repository is `bramvrensen/Hermes-Timesheet-Clerk`.

Normal installed-plugin update remains `timesheet_update`: fast-forward Git pull, compile/tests, runtime skill/profile wiring, frontend restart request and supervised Hermes gateway restart.

During recovery or major-version development, a manual pull inside the `hermes-agent` container followed by restarting `hermes-agent` and `timesheet-clerk-ui` is the deterministic fallback.

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
