# Simplicate booking

## 0.7.8 live assignment rehydration before booking

The 0.7.7 rollout exposed a separate assignment-mode bug. Persisted assignment mappings could contain the ID of `projecthourstype` itself instead of the nested Simplicate Hour Type. For the tested Kruitbosch assignment this produced a payload like:

```text
hour_type.id persisted: ef3f619c63b8e6b2b7aae5691f08671e
actual Senior Consultant hourstype: f902fc5514b044a2
```

The correct assignment path is:

```text
assignment.project.id
assignment.projectservice.id
assignment.projecthourstype.hourstype.id
```

`_normalize_assignment()` now stores the nested `hourstype` as the assignment's `hour_type` and keeps the project-hour-type relation ID separately as diagnostic metadata.

Single-task booking also no longer trusts persisted assignment metadata for the final POST. Immediately before preflight, Clerk fetches the current assignment for the entry date, replaces the stale in-memory assignment target with the live normalized target, builds the payload from that live target, and verifies that the outgoing `type_id` exists in current `GET /hours/hourstype` masterdata. If the assignment is no longer available or the Hour Type cannot be validated, the POST is blocked.

This means plans created before 0.7.8 do not need to be regenerated merely to repair stale assignment Hour Type IDs. After a successful verified booking the refreshed assignment target is persisted back into the plan revision.

## 0.7.7 project-service hour type relation IDs

`GET /projects/service` exposes `hour_types[]` as relation objects. The relation's own `id` is not a valid Simplicate hours `type_id`. The actual hour type is nested below the relation:

```text
service.hour_types[].hourstype.id
```

Earlier review-context normalization used `service.hour_types[].id`, so the UI could show the correct Hour Type name while persisting the project-service/hour-type relation ID. Prefix normalization cannot repair that semantic mismatch, and `POST /hours/hours` correctly responds with `Type is required`.

0.7.7 scopes editor Hour Types using the nested `hourstype.id` and nested name. The persistent review-context cache key is bumped to `v077` so stale relation IDs are not reused after upgrade.

Existing reviewed direct mappings created before 0.7.7 may still contain the old relation ID. Open the entry after upgrading, select the Hour Type from the freshly loaded scoped list and save the entry once before booking. Newly saved mappings will contain the real hour type ID.

## 0.7.6 authoritative Simplicate hours write contract

The live `POST /hours/hours` transport is field-specific. Timesheet Clerk no longer applies one generic ID-prefix rule to all booking fields.

Write identifiers are normalized as follows:

- `employee_id`: always `employee:<id>`;
- `project_id`: always `project:<id>`;
- `type_id`: always `hourstype:<id>` even when read-side data exposes `hourtype:<id>` or a UUID-like value;
- `assignment_id`: always `assignment:<id>` when booking planned work;
- `projectservice_id`: UUIDs with dashes are sent without a prefix; 32-character hexadecimal IDs are sent as `service:<id>`.

Direct/ad-hoc booking omits `assignment_id`. Assignment booking derives its target from the authoritative Simplicate assignment structure shown above.

Both booking modes explicitly send `billable`, `start_date`, `end_date`, `hours` and `note`. Compatibility fallbacks remain available for older Clerk state, but the final write payload always follows this endpoint contract.

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

## Write transaction

```text
latest persisted entry
        ↓
rehydrate assignment target when applicable
        ↓
validate outgoing Hour Type against live masterdata
        ↓
read existing Simplicate hours for the day
        ↓
receipt exists? → STOP
matching Simplicate row exists? → STOP
        ↓
POST exactly one /hours/hours registration
        ↓
WRITE RECEIPT IMMEDIATELY
        ↓
read Simplicate hours back
        ↓
matching registration found?
   yes → mark plan entry BOOKED in a new revision
   no  → leave receipt, report verification failure, block retry
```

The receipt-before-readback ordering prevents a second POST if the write succeeded but verification later fails.

## Idempotency and receipts

A receipt for the same `plan_id + entry_id` prevents another POST. Clerk also blocks a first POST when a probable matching Simplicate registration already exists. Receipts preserve plan/revision/entry identity, Clockify source IDs, the exact Simplicate request/response and verification state.

## Batch rollout

`Book day` should only be enabled after several production single-task bookings have completed and read back correctly. `Book week` should follow only after day booking has proven idempotent and fail-safe. Batch execution must reuse the same single-entry transaction semantics and stop on a non-idempotent failure.
