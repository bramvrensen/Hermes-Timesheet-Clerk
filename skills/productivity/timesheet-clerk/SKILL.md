---
name: timesheet-clerk
description: Prepare a reviewable weekly timesheet booking plan from Clockify and Simplicate. Use when planning, checking, reconciling or preparing hours for Simplicate.
---

# Timesheet Clerk

## Purpose

Prepare a deterministic, reviewable booking plan. Do not book hours while planning.

All `timesheet_*` capabilities are HERMES tools, not skills or shell scripts. Use the tool directly or, when deferred, use `tool_search` / `tool_describe` / `tool_call`. Never fall back to direct REST calls or terminal scripts while the Timesheet Clerk toolset is available.

The integration tools hide all Clockify/Simplicate transport details. Never reason about API prefixes, pagination, endpoint syntax, timezone workarounds or identifier formatting. Treat normalized tool output as the domain model.

## Planning workflow

1. Determine the requested week/period and local calendar dates.
2. Read relevant prior evidence with `timesheet_learning_context`.
3. Read Clockify entries for the complete period.
4. Read Simplicate context, planned assignments and already booked hours for the same period.
5. Reconcile already booked work before proposing new bookings.
6. For every unbooked Clockify entry, try planned-assignment-first mapping.
7. If no suitable planned assignment can be determined, use other evidence and validated booking assignments.
8. Only when no suitable assignment should be used, fall back to direct customer → project → task → hour-type mapping.
9. Build a sequential day plan. Never consolidate entries across calendar-day boundaries.
10. Persist a brand-new revision-1 plan with `timesheet_plan_create`. Do not overwrite a plan already under review and do not call a Simplicate booking/write capability during plan generation.

## booking_plan contract

Every generated plan uses `schema_version: 1`, starts at `revision: 1` and `status: DRAFT`, and contains:

- unique `plan_id`;
- `generated_at`;
- `week.monday` and `week.sunday`;
- `contract_hours_default: 36.0`;
- editable `target_hours` for this specific week;
- `entries`;
- `review_context` with normalized candidates needed by the deterministic review UI.

`review_context` should contain the relevant normalized `booking_assignments` and, where direct override is possible, normalized `customers`, `projects`, `services` and `hour_types`. It is review data, not hidden reasoning. Do not put credentials, transport-prefixed IDs or private chain-of-thought in the plan.

Each entry contains at minimum:

- stable `entry_id`;
- one or more `clockify_source_ids`;
- `date`;
- source context under `source` (description/project/client/tags);
- `original_duration_seconds` and `planned_duration_seconds`;
- `planned_start` and `planned_end` when a timeline is available;
- `booking_mode`: `assignment` or `direct`;
- `assignment` context for assignment mode, or `direct_mapping` for direct mode;
- `tier`: `AUTO`, `PROPOSE` or `ASK`;
- concise `mapping_source`, `field_tiers`, `why` and when useful `why_not_auto`;
- reconciliation/review state where applicable.

An unresolved ASK/PROPOSE entry may intentionally omit its final assignment/direct IDs so the user can resolve it in review. AUTO entries must be complete.

## Assignment-first policy

A Simplicate assignment is the preferred booking target because it represents the employee/project/task/hour-type combination.

Distinguish:

- planned assignments: active employee assignments with `is_planned = true`, both start and end dates, overlapping the requested date. These are primary planning evidence;
- booking assignments: credible active booking/override targets. Undated records may appear here but are never planning evidence by themselves.

For an entry, first evaluate planned assignments for that entry date. If one reliable match exists, assignment mode is preferred. If multiple relevant planned assignments remain plausible, do not silently choose one for AUTO. Other booking assignments can support a proposal or override but their mere existence is weaker evidence. If no suitable assignment exists, use direct mapping.

When an assignment is selected, its customer/project/task/hour type are derived context, not independent choices.

## Autonomy

Use `AUTO`, `PROPOSE`, and `ASK`. Autonomy is evidence based. Confidence is a supporting signal, not a numeric business threshold.

Evidence may include explicit user rules, confirmed scoped rules, exact precedents, successful prior applications, current planned-assignment context, Clockify client/project context and semantic similarity. Semantic similarity alone must not yield AUTO. An undated booking assignment alone is not planning evidence.

Conflicting evidence lowers autonomy. Missing or invalid masterdata blocks AUTO. If a relevant planned assignment exists but the correct assignment is ambiguous, the entry must not be AUTO.

For PROPOSE/ASK, use compact provenance such as `conflicting_rules`, `semantic_match_only`, `missing_masterdata`, `stale_precedent`, `new_client`, `booking_assignment_only`, or `low_match_specificity`. Do not expose private chain-of-thought.

## Learning

Review feedback is evidence, not an immediate global rule:

```text
feedback event → precedent → candidate rule → confirmed rule
       ▲                                      │
       └──────── success/correction feedback ─┘
```

Rules must be scoped. A generic description such as `Projectoverleg` must never become a global AUTO rule through repetition alone. A corrected AUTO decision is strong negative evidence. Degrade or deactivate the relevant inferred rule according to the evidence and current policy.

`timesheet_learning_context` returns append-only feedback plus current agent-derived rules. Read it before planning when prior behavior may be relevant. The storage layer never promotes or generalizes rules on its own.

## Week hours

The default contractual week is 36 hours. Completeness checks use the plan's editable `target_hours`, never a hardcoded 36/40 hour threshold.

## Safety

- Planning/API-read tools and plan persistence are separate from Simplicate writes.
- Never book during plan generation.
- Never invent Simplicate IDs or assignments.
- Never reinterpret a tool error as successful data.
- If reconciliation is ambiguous, surface the conflict instead of marking an entry BOOKED.
- Never overwrite a plan that is already in review; a new agent run creates a new `plan_id`.
