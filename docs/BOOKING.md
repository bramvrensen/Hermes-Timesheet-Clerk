# Simplicate booking

## 0.7.4 inline confirmation inside Review

The Review entry editor is already a Streamlit dialog. Streamlit does not allow one `st.dialog` to open another `st.dialog`, so task booking confirmation is rendered inline inside the existing Review dialog.

The flow is now:

```text
Review / edit
    ↓
Book task
    ↓
inline Simplicate preflight + human-readable target/date/duration
    ↓
explicit checkbox
    ↓
Confirm booking
```

No second modal is created. Cancel simply collapses the inline confirmation block. The booking transaction itself is unchanged.

## 0.7.3 booking-target normalization

The working-plan contract stores direct mappings canonically as `project_id`, `service_id` and `hour_type_id`, while older plans and Simplicate-shaped data may expose equivalent values as `projectservice_id`, `type_id` or nested `project`, `projectservice`/`service`, and `hour_type`/`type` objects.

Single-task booking normalizes these representations before validating the target and constructing the Simplicate POST. Canonical working-plan fields always win when both representations exist. This compatibility layer is intentionally inside the booking boundary: persisted reviewed state is not silently rewritten merely to satisfy transport naming.

A human-readable target shown in the review card is not sufficient evidence by itself. The booking boundary still requires real IDs for project, project service and hour type after normalization before any POST is attempted.

## 0.7.2 shared Simplicate configuration

The Streamlit review frontend and the Hermes planner runtime do not necessarily inherit the same process environment. Booking therefore uses the same shared configuration resolver as the rest of Timesheet Clerk.

`SimplicateConfig.from_env()` first preserves any integration variables already present in the process and then fills only missing Clockify/Simplicate integration values from the configured planner profile `.env` (normally `/home/hermes/.hermes/profiles/atlas/.env`). No second set of booking credentials is introduced.

This means Simplicate review reads and live task writes use the same source configuration, including `SIMPLICATE_BASE_URL`, API key/secret and employee ID.

## 0.7.0 validation phase

0.7.0 introduces the first live Simplicate write path. Live writes are deliberately enabled only for a single persisted task from the Review dialog.

Visible controls:

- `Book task`: active for a persisted bookable entry;
- `Book day`: visible but disabled during single-task validation;
- `Book week`: visible but disabled during single-task validation.

The user never has to inspect raw Simplicate JSON payloads. The inline confirmation surface shows the human booking target, date, planned time and duration.

## Book-task eligibility

A task is bookable when:

- it is not ignored/skipped;
- it is not already marked `BOOKED`;
- it has a complete assignment/direct mapping;
- PROPOSE/ASK entries have been human confirmed or corrected;
- AUTO entries have a valid resolved target and may be explicitly booked by the user.

The booking action always uses the latest persisted revision. Unsaved editor controls are never sent to Simplicate. Save a correction first, then book the task.

## Write transaction

The guarded single-task transaction is:

```text
latest persisted entry
        ↓
validate booking eligibility
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

The receipt-before-readback ordering is intentional. If the POST succeeds but the subsequent GET/network path fails, Timesheet Clerk must never repeat the POST automatically.

## Idempotency

A Timesheet Clerk receipt for the same `plan_id + entry_id` prevents another POST.

Before a first POST, Clerk also searches existing Simplicate hours for a registration matching project, project service, hour type, assignment where applicable, date and duration. A probable pre-existing match blocks the write rather than guessing whether it belongs to Clerk.

## Receipts

Receipts live in shared Clerk state under `receipts/` and contain:

- plan/revision/entry identity;
- underlying Clockify source IDs;
- the exact Simplicate request;
- the Simplicate response;
- timestamp and verification state.

Receipts are durable safety artifacts and are not coupled to mutable working-revision retention.

## Batch rollout

`Book day` should only be enabled after several production single-task bookings have completed and read back correctly. `Book week` should only be enabled after day booking has proven idempotent and fail-safe.

Batch execution must reuse the same single-entry transaction semantics and stop immediately on a non-idempotent failure. A batch must never retry a task that already has a receipt.
