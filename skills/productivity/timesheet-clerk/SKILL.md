---
name: timesheet-clerk
description: Prepare a reviewable weekly timesheet booking plan from Clockify and Simplicate. Use when planning, checking, reconciling or preparing hours for Simplicate.
---

# Timesheet Clerk 0.6.4

## Core contract
Timesheet Clerk owns plan structure, source truth, scheduling and state. HERMES owns mapping decisions only.

Never construct, edit, serialize or infer booking-plan JSON. Never use terminal, execute_code, filesystem or generic file tools for Clerk state. On any Clerk tool error, stop and report the exact error.

## Create / refresh
1. Call `timesheet_mapping_prepare` for the exact Monday/Sunday and requested `rebuild` flag.
2. If `no_op=true`, stop and present the deterministic summary.
3. Process exactly the returned `work_items`.
4. Read only the config, learning and Simplicate context needed for those work items.
5. Produce exactly one mapping decision per `source_id`.
6. Call `timesheet_mapping_apply` exactly once with the same rebuild flag.
7. Present the deterministic summary returned by the tool.

A refresh started with `rebuild=false` may never escalate itself to `rebuild=true`. Rebuild requires a new explicit user action/request.

## Mapping decisions
For `ignored=true`, do not invent a booking target. Booking mode may be omitted. Python normalizes ignored rows as covered but intentionally non-bookable.

### Unknown is not ignored
Lack of information is never a valid reason to discard time. Blank descriptions, `?`, `??`, `?? -- ??`, `unknown`, `onbekend` or otherwise unclassified work must remain non-ignored and `ASK` until a human classifies it. Python enforces recognized unknown placeholders even if HERMES incorrectly returns `ignored=true`.

Use ignored only when there is positive evidence that the source must not be booked, such as an established travel/lunch exclusion rule.

## Scheduling
HERMES does not choose planned start/end times. Python owns the canonical daily timeline.

For every day:
- ignored rows do not participate in the booking timeline;
- non-billable/internal work is scheduled before billable work;
- the first non-ignored entry starts at 09:00;
- following entries are contiguous using `planned_duration_seconds`;
- the same scheduling engine runs after create/refresh and human review edits such as duration, restore, skip or mapping changes.

Clockify timestamps remain immutable source evidence.

## Review safety
A restored ignored entry that has no complete booking target must reopen as `ASK/PENDING`; it must never become a resolved AUTO entry merely because `ignored` changed to false.

Human-reviewed booking targets remain authoritative on later incremental refreshes. Approved snapshots are immutable. Never book hours during generation, refresh or rebuild.

## Removed Clockify sources
Safe single-source removals are reconciled deterministically. Partial loss from a legacy consolidated bundle returns `requires_explicit_rebuild`; this is not permission to retry automatically.

## Updates
When asked to update Timesheet Clerk, use `timesheet_update`. Do not improvise source-code recovery from inside an active planner run.
