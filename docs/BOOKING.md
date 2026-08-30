# Simplicate booking

## 0.7.16 canonical batch booking UI

`Book day` and `Book week` now live in the canonical `frontend/review_app.py` render path itself. The previous architecture left hard-coded `disabled=True` placeholder buttons in `review_app.py` and depended on `frontend/app.py` monkeypatches to replace them at runtime. That split made deployments fragile and allowed a permanently disabled legacy control to remain visible even while the batch-booking implementation was correct elsewhere.

The canonical day renderer now calls `render_day_booking(...)` directly and the canonical week footer calls `render_week_booking(...)` directly. `frontend/app.py` no longer adds a second week-booking control. Regression tests fail if the old hard-coded disabled controls return or if the wrapper renders a duplicate week button.

The batch button is disabled only when the selected day/week contains no open entries at all. When open entries exist, clicking the button always opens an eligibility view. Eligible entries proceed to preflight; ineligible entries remain in review with their explicit reason.

## 0.7.12 approval idempotency and visible batch blockers

`READY` is a reviewed, not-yet-booked state and is visually distinct from both `AUTO` and grey `BOOKED` rows.

When `Book day` or `Book week` is disabled, the UI now lists the exact blocking entries and the reason returned by the booking-readiness check. This makes unresolved review state, incomplete targets and other blockers explicit instead of showing only a disabled button.

Approving the same unchanged `plan_id + revision` is idempotent. The first approval creates an immutable snapshot with `approved_at`; subsequent approval attempts compare the actual plan content while ignoring the timestamp-only `approved_at` field and return the existing snapshot when content is unchanged. A genuine content mismatch for the same revision still raises a conflict.

## 0.7.10 task, day and week booking

0.7.10 extends the proven thin `Book task` boundary to `Book day` and `Book week`.

Batch booking only includes open, non-ignored entries. Every open entry in the selected day/week must already be review-complete and have a complete persisted booking target. Mapping validity is not refreshed at booking time; `Generate / refresh plan` remains the Simplicate synchronization boundary.

A day/week preflight performs one booked-hours read across the selected date range and checks every selected payload for receipts and probable duplicates. Any probable duplicate blocks the whole batch before writes. After explicit confirmation, rows are posted sequentially and each successful POST gets its own receipt and immediate readback verification. A rejected POST writes no receipt, remains open for review, and does not prevent later independent rows from being attempted.

The Review page remembers the entry anchor before opening its dialog so closing/re-running the editor returns the main page to the same time-entry card rather than the top of the week.

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
