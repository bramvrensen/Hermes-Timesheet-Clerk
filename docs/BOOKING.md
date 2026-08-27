# Simplicate booking

## 0.7.9 Generate / Refresh is the Simplicate synchronization boundary

Timesheet Clerk now treats `Generate / refresh plan` as the single point where current Simplicate masterdata is authoritative for mapping.

A generation run:

```text
fetch complete Clockify week
        +
fetch one complete Simplicate generation context
        ↓
prepare mapping work
        ↓
validate mapping decisions against that same Simplicate snapshot
        ↓
persist reviewed plan state
```

`timesheet_mapping_prepare` captures the Simplicate context once and stores it as the generation snapshot. The returned `simplicate_context` is also the context Hermes must use for its mapping decisions. `timesheet_mapping_apply` reuses the stored snapshot rather than fetching Simplicate again.

A mapping can only remain resolved when its target exists in that snapshot. Assignment mappings require the assignment to exist. Direct mappings require a valid project, a service belonging to that project, and an Hour Type explicitly scoped to that service. Assignment decisions are canonicalized to the assignment object from the snapshot.

On later Generate / Refresh runs, existing resolved mappings are checked against the newly captured Simplicate snapshot. If an assignment, service or scoped Hour Type has disappeared, the affected Clockify source is returned as mapping work again. An invalid prior target is not preserved merely because it was previously human reviewed.

### Thin booking

Booking no longer re-fetches assignments, services or Hour Type masterdata. The reviewed plan is the booking instruction produced by the most recent generation snapshot.

`Book task` therefore performs only:

```text
persisted reviewed entry
        ↓
one duplicate check against booked hours
        ↓
POST /hours/hours
        ↓
WRITE RECEIPT IMMEDIATELY after successful POST
        ↓
one booked-hours readback
        ↓
verified → BOOKED
```

The duplicate preflight is cached per `plan_id + revision + entry_id` in the Streamlit session, so checkbox changes and rerenders do not repeat the Simplicate check. Confirmation can reuse that preflight only while the plan revision is unchanged.

If Simplicate masterdata changes in the small window between generation and booking, the POST may be rejected. That is intentional: a rejected POST writes no receipt and the entry remains reviewable so it can be mapped to another target. The next Generate / Refresh sees the changed Simplicate state automatically.

This boundary is also the basis for future `Book day` and `Book week`: mapping validation is performed once during generation, while booking can batch duplicate/readback checks instead of repeatedly downloading masterdata for every task.

## 0.7.8 assignment Hour Type correction

0.7.8 established the correct assignment target path after persisted assignment mappings were found to contain the ID of `projecthourstype` itself rather than the nested Simplicate Hour Type:

```text
assignment.project.id
assignment.projectservice.id
assignment.projecthourstype.hourstype.id
```

`_normalize_assignment()` stores the nested `hourstype` as the assignment's `hour_type` and keeps the project-hour-type relation ID separately as diagnostic metadata. 0.7.9 moves the freshness check for this data from booking time to the generation snapshot described above.

## 0.7.7 project-service hour type relation IDs

`GET /projects/service` exposes `hour_types[]` as relation objects. The relation's own `id` is not a valid Simplicate hours `type_id`. The actual hour type is nested below the relation:

```text
service.hour_types[].hourstype.id
```

Earlier review-context normalization used `service.hour_types[].id`, so the UI could show the correct Hour Type name while persisting the project-service/hour-type relation ID. Prefix normalization cannot repair that semantic mismatch, and `POST /hours/hours` correctly responds with `Type is required`.

0.7.7 scopes editor Hour Types using the nested `hourstype.id` and nested name. The persistent review-context cache key is `v077` so stale relation IDs are not reused after upgrade.

## 0.7.6 authoritative Simplicate hours write contract

The live `POST /hours/hours` transport is field-specific. Timesheet Clerk does not apply one generic ID-prefix rule to all booking fields.

Write identifiers are normalized as follows:

- `employee_id`: always `employee:<id>`;
- `project_id`: always `project:<id>`;
- `type_id`: always `hourstype:<id>`;
- `assignment_id`: always `assignment:<id>` when booking planned work;
- `projectservice_id`: UUIDs with dashes are sent without a prefix; 32-character hexadecimal IDs are sent as `service:<id>`.

Direct/ad-hoc booking omits `assignment_id`. Both booking modes explicitly send `billable`, `start_date`, `end_date`, `hours` and `note`.

## 0.7.5 safe Simplicate rejection diagnostics

Simplicate validation failures arrive in the shared HTTP layer as an `IntegrationError` containing the HTTP status and parsed response details. The single-task booking UI shows the Clerk error message, HTTP status code and parsed Simplicate response details while never exposing authentication headers or secrets. A rejected POST does not write a Clerk receipt.

## 0.7.4 inline confirmation inside Review

The Review entry editor is already a Streamlit dialog. Task booking confirmation is therefore rendered inline inside that existing dialog rather than attempting to nest dialogs.

## 0.7.3 booking-target normalization

The working-plan contract stores direct mappings canonically as `project_id`, `service_id` and `hour_type_id`. Booking normalizes older Simplicate-shaped aliases at the write boundary, but still requires real IDs for project, project service and hour type.

## 0.7.2 shared Simplicate configuration

The Streamlit review frontend and Hermes planner use the same `SimplicateConfig.from_env()` resolver. Missing integration variables are filled from the configured planner profile `.env`; no second booking credential set exists.

## 0.7.0 validation phase

0.7.0 introduced the first live write path as task-by-task booking. `Book day` and `Book week` remain locked until single-task booking has been proven in production.

## Book-task eligibility

A task is bookable when it is not ignored/skipped, is not already `BOOKED`, has a complete mapping, and any PROPOSE/ASK mapping has been human confirmed or corrected. Unsaved editor controls are never sent to Simplicate.

## Idempotency and receipts

A receipt for the same `plan_id + entry_id` prevents another POST. Clerk also blocks a first POST when a probable matching Simplicate registration already exists. Receipts preserve plan/revision/entry identity, Clockify source IDs, the exact Simplicate request/response and verification state.

## Batch rollout

`Book day` should only be enabled after several production single-task bookings have completed and read back correctly. `Book week` should follow only after day booking has proven idempotent and fail-safe. Batch execution must reuse the same receipt/idempotency semantics and stop on a non-idempotent failure.
