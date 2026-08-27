# Simplicate booking

## 0.7.0 validation phase

0.7.0 introduces the first live Simplicate write path. Live writes are deliberately enabled only for a single persisted task from the Review dialog.

Visible controls:

- `Book task`: active for a persisted bookable entry;
- `Book day`: visible but disabled during single-task validation;
- `Book week`: visible but disabled during single-task validation.

The user never has to inspect raw Simplicate JSON payloads. The confirmation dialog shows the human booking target, date, planned time and duration.

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
