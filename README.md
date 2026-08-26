# HERMES Timesheet Clerk

Human-in-the-loop timesheet planning and booking for HERMES Agent.

> Status: **0.6.2 deterministic planner.** Clockify/Simplicate reads, mapping-decision orchestration, source reconciliation, review UI, feedback, approvals, safe week rebuilds and explicit current-week generation are available. Simplicate writes remain deliberately disabled until the booking path is validated.

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

The planner no longer receives tools that can create/sync arbitrary plan JSON, rebaseline state or destructively reset a week.

## 0.6.2 current-week generation

0.6.2 separates **the plan currently open in the frontend** from **whether the current calendar week already has a working plan**.

A historical week may remain active for review without hiding the action to create the current week. If, for example, week 34 is open while week 35 does not yet exist, the Review tab shows `Generate current week` for week 35.

Current-week creation uses `rebuild=false`. Because no working plan exists for that exact week, the deterministic core treats the run as CREATE. Historical plans remain untouched.

The frontend checks the plan catalog for the exact Monday/Sunday rather than relying on the global active pointer.

## 0.6.1 source reconciliation

0.6.1 fixes legacy/orphan source references that can exist in a working plan even when the historic Clockify snapshot baseline no longer contains them.

Removed Clockify detection is based on live Clockify IDs versus actual plan coverage, not snapshot history alone.

- A one-source plan row whose Clockify source disappeared is removed deterministically during normal refresh.
- A legacy consolidated row whose complete source bundle disappeared is removed deterministically.
- If only part of a legacy consolidated bundle disappeared, Timesheet Clerk returns `requires_explicit_rebuild` instead of guessing how the historic aggregate should be split.
- A normal refresh may never automatically retry as a rebuild. `rebuild=false` stays false for the entire planner run; rebuild requires an explicit user action/request.

## Safety

- `timesheet_plan_create`, `timesheet_plan_sync`, `timesheet_source_rebaseline` and `timesheet_plan_fresh_start` are removed from the HERMES tool surface.
- Legacy destructive `fresh_start_week()` is disabled in code.
- Rebuild is create-before-switch: the existing plan remains available until a complete replacement has been built and validated.
- Failed rebuilds leave existing plan state untouched.
- Missing `active_plan.json` is repaired from the stored plan catalog instead of being interpreted as an empty repository.
- Background planner jobs persist `STARTING/RUNNING/SUCCEEDED/FAILED` state and an exit code. A vanished runner becomes `FAILED`, never an eternal `RUNNING` state.
- Runtime `SKILL.md` is migrated with a mandatory versioned guard because the live skill intentionally lives outside Git.
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

Removed sources need no mapping decision. They are reconciled deterministically by Python when safe to do so.

## Safe rebuild

A rebuild uses the same two tools with `rebuild=true`, but only after explicit user intent. The old plan is not deleted first. The plugin builds a complete replacement, validates Clockify coverage and the plan contract, writes the new plan, activates it and then best-effort marks the old working plan `SUPERSEDED`.

A tool failure before successful creation leaves the old plan available.

## Review UI

The Streamlit frontend provides week/day views, modal review/editing, skip/restore, duration reflow, assignment/direct mapping overrides, configuration, runtime SKILL editing, state inspection, approvals and booking preparation.

If the active pointer is missing but stored plans exist, the UI repairs the pointer and opens the newest stored plan. Configuration, SKILL and State remain accessible even when no plan exists.

If the current calendar week has no working plan, `Generate current week` remains available even while an older week is open.

Planner status is shown in the frontend as a real job state rather than inferred only from a PID.

## Source integrity

A normalized Clockify row is source truth. Source comparison tracks ID, description, client, project, tags, start/end timestamps and duration. Simplicate mapping, planned duration, ignore/review state and booking state do not redefine the source.

Actual plan coverage is also checked against the live Clockify week. This protects reconciliation when historic source snapshots are incomplete or stale.

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
