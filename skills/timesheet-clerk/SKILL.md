---
name: timesheet-clerk
description: Prepare a reviewable weekly timesheet booking plan from Clockify and Simplicate. Use when planning, checking, reconciling or preparing hours for Simplicate.
---

# Timesheet Clerk

## Purpose

Prepare a deterministic, reviewable booking plan. Do not book hours while planning.

The integration tools hide all Clockify/Simplicate transport details. Never reason about API prefixes, pagination, endpoint syntax, timezone workarounds or identifier formatting. Treat normalized tool output as the domain model.

## Planning workflow

1. Determine the requested week/period and its local calendar dates.
2. Read Clockify entries for the complete period.
3. Read Simplicate context, assignments and already booked hours for the same period.
4. Reconcile already booked work before proposing new bookings.
5. For every unbooked Clockify entry, try **assignment-first mapping**.
6. Only when no suitable assignment can be determined, use direct customer → project → task → hour-type mapping.
7. Build a sequential day plan. Never consolidate entries across calendar-day boundaries.
8. Produce/update the versioned `booking_plan.json` contract. Do not call a booking/write capability during this workflow.

## Assignment-first policy

A Simplicate assignment is the preferred booking target because it represents the valid employee/project/task/hour-type combination.

When evaluating an entry:

- prefer assignments valid for the entry date;
- use Clockify client/project/description plus other permitted context to distinguish assignments;
- an exact or strongly contextual assignment match is stronger evidence than reconstructing a direct mapping;
- if multiple relevant assignments remain plausible, do not silently choose one for AUTO;
- if no suitable assignment exists, fall back to direct mapping.

When an assignment is selected, its underlying project/task/hour type are derived context, not independent choices.

## Autonomy

Use `AUTO`, `PROPOSE`, and `ASK` as review tiers.

Autonomy is evidence based. Never apply rules such as "seen twice means AUTO". Confidence is a supporting signal, not a numeric business threshold.

Evidence sources may include:

- explicit user rules;
- confirmed scoped rules;
- exact precedents;
- successful prior applications;
- current Simplicate assignment/planning context;
- Clockify client/project context;
- semantic similarity.

Semantic similarity alone must not yield AUTO.

Conflicting evidence lowers autonomy. Missing or invalid masterdata blocks AUTO. If a relevant assignment exists but the correct assignment is ambiguous, the entry must not be AUTO.

For PROPOSE/ASK, record a compact `why_not_auto` where useful. Do not expose private chain-of-thought. Use concise provenance such as `conflicting_rules`, `semantic_match_only`, `missing_masterdata`, `stale_precedent`, `new_client`, or `low_match_specificity`.

## Learning

Review feedback is evidence, not an immediate global rule.

Conceptual progression:

```text
feedback event → precedent → candidate rule → confirmed rule
       ▲                                      │
       └──────── success/correction feedback ─┘
```

Rules must be scoped. A generic description such as "Projectoverleg" must never become a global AUTO rule merely through repetition.

A corrected AUTO decision is strong negative evidence. Degrade or deactivate the relevant inferred rule according to the available evidence.

## Week hours

The default contractual week is 36 hours, but the plan has an editable `target_hours` for the specific week. Completeness checks use `target_hours`, not the default contract value.

## Safety

- Planning tools are read-only.
- Never book during plan generation.
- Never invent Simplicate IDs or assignments.
- Never reinterpret a tool error as successful data.
- If reconciliation is ambiguous, surface the conflict instead of marking an entry BOOKED.
