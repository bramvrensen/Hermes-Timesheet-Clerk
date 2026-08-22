---
name: timesheet-clerk
description: Prepare a reviewable weekly timesheet booking plan from Clockify and Simplicate. Use when planning, checking, reconciling or preparing hours for Simplicate.
---

# Timesheet Clerk

## Purpose

Prepare a deterministic, reviewable weekly booking plan. Do not book hours while planning.

All `timesheet_*` capabilities are HERMES tools. Use the tools directly and never fall back to direct REST calls or terminal scripts while the Timesheet Clerk toolset is available.

The integration tools hide Clockify/Simplicate transport details. Treat normalized tool output as the domain model.

## Runtime policy

At the start of every planning or synchronization run, call `timesheet_config_get` and use the returned runtime policy. The runtime config is user-managed state and overrides default numeric policy values in this template.

Relevant settings include:

- `planner_profile`;
- `contract_hours_default`;
- `auto_confidence_threshold`;
- `propose_confidence_threshold`;
- `semantic_similarity_auto_allowed`;
- `require_strong_evidence_for_auto`;
- `prefer_planned_assignment`;
- retention settings.

Confidence thresholds are supporting policy boundaries. Evidence quality still matters. Missing masterdata, contradictory evidence or ambiguous planned assignments may never be upgraded to AUTO merely because a numeric score clears the configured threshold.

## Weekly sync workflow

1. Determine the requested week and local calendar dates.
2. Read `timesheet_config_get`.
3. Read relevant prior evidence with `timesheet_learning_context`.
4. Read Clockify entries for the complete period.
5. Read Simplicate context, planned assignments and already booked hours for the same period.
6. Reconcile already booked work before proposing new bookings.
7. For every unbooked Clockify entry, try planned-assignment-first mapping when runtime policy enables it.
8. If no suitable planned assignment can be determined, use other evidence and validated booking assignments.
9. Only when no suitable assignment should be used, fall back to direct customer → project → task → hour-type mapping.
10. Build or refresh the sequential day plan. Never consolidate entries across calendar-day boundaries.
11. Persist through `timesheet_plan_sync`. This creates a week plan if none exists, otherwise synchronizes the existing open week in place.
12. Never call a Simplicate booking/write capability during generation or sync.

A repeated run in the same open week is a sync, not a new plan. New Clockify entries are appended, changed source entries are refreshed, and human-reviewed values are preserved. Planner synchronization does not create a new human-review revision.

## Working-plan lifecycle

The open plan is mutable working state. Human review changes create revisions; repeated planner syncs do not.

Use these lifecycle concepts:

- `DRAFT`: generated/synchronized but not yet materially reviewed;
- `IN_REVIEW`: the user has made review changes;
- `APPROVED`: immutable approved snapshot used as booking input;
- `BOOKED`: booking completed and receipts exist.

Never silently overwrite a human-reviewed entry during a later sync. If new source evidence conflicts with a confirmed/corrected/skipped entry, preserve the reviewed values and surface the changed source context for review.

## booking_plan contract

Every plan uses `schema_version: 1` and contains:

- stable `plan_id` for the working week;
- `revision` for human review history;
- `generated_at` and optional `source_sync_at`;
- `week.monday` and `week.sunday`;
- `contract_hours_default`;
- editable `target_hours`;
- `entries`;
- normalized `review_context` where available.

Each entry contains at minimum:

- stable `entry_id`;
- one or more `clockify_source_ids`;
- `date`;
- source context under `source`;
- `original_duration_seconds` and `planned_duration_seconds`;
- `planned_start` and `planned_end` when a timeline is available;
- `booking_mode`: `assignment` or `direct`;
- `assignment` context for assignment mode, or `direct_mapping` for direct mode;
- `tier`: `AUTO`, `PROPOSE` or `ASK`;
- concise `mapping_source`, `field_tiers`, `why` and when useful `why_not_auto`;
- reconciliation/review state where applicable.

An unresolved ASK/PROPOSE entry may omit final IDs so the user can resolve it in review. AUTO entries must be complete.

## Assignment-first policy

A Simplicate assignment is normally the preferred booking target because it represents the employee/project/task/hour-type combination.

Distinguish:

- planned assignments: active employee assignments with `is_planned = true`, dated and overlapping the requested date. These are primary planning evidence;
- booking assignments: credible active booking/override targets. Undated records are never planning evidence by themselves.

If multiple relevant planned assignments remain plausible, do not silently choose one for AUTO. If no suitable assignment exists, use direct mapping.

When an assignment is selected, its customer/project/task/hour type are derived context, not independent choices.

## Autonomy

Use `AUTO`, `PROPOSE`, and `ASK` according to runtime config plus evidence quality.

Evidence may include explicit user rules, confirmed scoped rules, exact precedents, successful prior applications, current planned-assignment context, Clockify client/project context and semantic similarity.

Unless runtime config explicitly enables it, semantic similarity alone must not yield AUTO. Even when enabled, ambiguity, conflicting evidence or missing masterdata blocks AUTO.

For PROPOSE/ASK, use compact provenance such as `conflicting_rules`, `semantic_match_only`, `missing_masterdata`, `stale_precedent`, `new_client`, `booking_assignment_only`, or `low_match_specificity`. Do not expose private chain-of-thought.

## Learning

Review feedback is evidence, not an immediate global rule:

```text
feedback event → precedent → candidate rule → confirmed rule
       ▲                                      │
       └──────── success/correction feedback ─┘
```

Rules must be scoped. A generic description such as `Projectoverleg` must never become a global AUTO rule through repetition alone. A corrected AUTO decision is strong negative evidence.

`timesheet_learning_context` returns append-only feedback plus current agent-derived rules. Read it before planning when prior behavior may be relevant.

## Week hours

Use the plan's editable `target_hours` for completeness checks. The default comes from runtime config, not a hardcoded 36/40 hour assumption.

## Safety and retention

- Planning/API-read tools and plan persistence are separate from Simplicate writes.
- Never book during plan generation or synchronization.
- Never invent Simplicate IDs or assignments.
- Never reinterpret a tool error as successful data.
- If reconciliation is ambiguous, surface the conflict instead of marking an entry BOOKED.
- Approved booking input is immutable.
- After successful booking, the approved snapshot actually used for booking plus booking receipts are the audit artifacts. Working plan/revision clutter may be purged according to runtime policy.
- Feedback and learned rules are retained as learning history unless runtime policy explicitly says otherwise.
