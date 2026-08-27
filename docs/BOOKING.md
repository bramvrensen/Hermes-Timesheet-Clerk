# Simplicate booking

## 0.7.10 task, day and week booking

0.7.10 extends the proven thin `Book task` boundary to `Book day` and `Book week`.

Batch booking only includes open, non-ignored entries. Every open entry in the selected day/week must already be review-complete and have a complete persisted booking target. Mapping validity is not refreshed at booking time; `Generate / refresh plan` remains the Simplicate synchronization boundary.

A day/week preflight performs one booked-hours read across the selected date range and checks every selected payload for receipts and probable duplicates. Any probable duplicate blocks the whole batch before writes. After explicit confirmation, rows are posted sequentially and each successful POST gets its own receipt and immediate readback verification. A rejected POST writes no receipt, remains open for review, and does not prevent later independent rows from being attempted.

The Review page now remembers the entry anchor before opening its dialog so closing/re-running the editor returns the main page to the same time-entry card rather than the top of the week.

## 0.7.9 Generate / Refresh is the Simplicate synchronization boundary

Timesheet Clerk treats `Generate / refresh plan` as the single point where current Simplicate masterdata is authoritative for mapping.

A generation run fetches the complete Clockify week and one complete Simplicate generation context, prepares mapping work, validates mapping decisions against that same Simplicate snapshot, and persists reviewed plan state. Existing resolved mappings are checked again on later refreshes; targets that disappeared become mapping work again.

### Thin booking

Booking does not re-fetch assignments, services or Hour Type masterdata. The reviewed plan is the booking instruction produced by the most recent generation snapshot.

`Book task` performs one duplicate check, `POST /hours/hours`, writes a receipt immediately after a successful POST, then performs one booked-hours readback. The duplicate preflight is cached per `plan_id + revision + entry_id` in the Streamlit session.

If Simplicate masterdata changes between generation and booking, the POST may be rejected. A rejected POST writes no receipt and the entry remains reviewable. The next Generate / Refresh sees the changed Simplicate state.

## Simplicate write contract

Assignment targets use `assignment.project.id`, `assignment.projectservice.id` and `assignment.projecthourstype.hourstype.id`. Project-service `hour_types[]` are relation objects; the valid Hour Type is `service.hour_types[].hourstype.id`, not the relation ID itself.

Write identifiers are normalized as follows:

- `employee_id`: `employee:<id>`;
- `project_id`: `project:<id>`;
- `type_id`: `hourstype:<id>`;
- `assignment_id`: `assignment:<id>` for planned work;
- `projectservice_id`: UUIDs with dashes are sent without a prefix; 32-character hexadecimal IDs are sent as `service:<id>`.

Direct/ad-hoc booking omits `assignment_id`. Both modes send `billable`, `start_date`, `end_date`, `hours` and `note`.

## Error handling and idempotency

Simplicate validation failures are shown with HTTP status and parsed response details without exposing authentication headers or secrets. A rejected POST does not write a Clerk receipt.

A receipt for the same `plan_id + entry_id` prevents another POST. Clerk also blocks a first POST when a probable matching Simplicate registration already exists. Receipts preserve plan/revision/entry identity, Clockify source IDs, the exact Simplicate request/response and verification state.
