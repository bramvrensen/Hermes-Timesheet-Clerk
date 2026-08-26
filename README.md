# HERMES Timesheet Clerk

Human-in-the-loop timesheet planning and booking for HERMES Agent.

> Status: **0.6.6 deterministic planner.** Clockify/Simplicate reads, decisions-only mapping orchestration, source reconciliation, review UI, deterministic day scheduling, reviewed-entry consolidation, human duration display, service-scoped hour type selection, feedback, approvals, safe week rebuilds and current-week generation are available. Simplicate writes remain deliberately disabled until the booking path is validated.

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

## 0.6.6 reviewed consolidation and human time display

Human review can now consolidate adjacent entries after a correction/restore workflow. Consolidation is deliberately conservative: both rows must be non-ignored, resolved, human-confirmed/corrected, contiguous in planned time, have the exact same booking target and billable state, and represent the same Clockify work context/description. Matching rows are merged into one visible booking block while all underlying `clockify_source_ids` and snapshots remain available for coverage and later splitting.

Example: two reviewed Cyclovriend `Reistijd` rows of one hour each, mapped to the same Simplicate travel code, become one `09:00–11:00` block of `2u`.

Duration presentation no longer uses decimal-hour notation. Review cards, day summaries and week metrics use human labels such as `15 min`, `30 min`, `1u`, `1u 30 min` and `2u`. Clockify source durations use the same presentation.

## 0.6.5 service-scoped hour types

Direct-mapping review treats the Simplicate Task / service as the parent of the Hour type choice.

- selecting a Task / service filters the Hour type dropdown to rows whose `service_id` exactly matches the selected service;
- global/unscoped hour types are never offered as a fallback;
- duplicate hour types are removed by ID;
- the configured preferred hour type is only prioritized inside the valid scoped set;
- if Simplicate exposes no valid hour types for the selected service, the UI shows a warning and the mapping remains incomplete.

## 0.6.4 review and scheduling

The daily booking timeline is deterministic:

- ignored rows remain source-covered but do not participate in the booking timeline;
- non-billable/internal entries are scheduled before billable entries;
- the first non-ignored entry starts at 09:00;
- following entries are contiguous using `planned_duration_seconds`;
- the same reflow runs after CREATE/REFRESH and human review changes such as duration, skip, restore and mapping edits.

Restore is fail-safe: restoring an ignored entry without a complete target reopens it as `ASK/PENDING` rather than fabricating a resolved mapping.

Unclassified time is never silently discarded. Blank descriptions and recognized placeholders such as `?`, `??`, `?? -- ??`, `unknown` and `onbekend` are forced back to non-ignored `ASK` state.

Simplicate review context is fetched concurrently and cached per week for 30 minutes in shared Clerk state, substantially reducing frontend load time.

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
