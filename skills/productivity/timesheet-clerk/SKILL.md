---
name: timesheet-clerk
description: Prepare a reviewable weekly timesheet booking plan from Clockify and Simplicate. Use when planning, checking, reconciling or preparing hours for Simplicate.
---

# Timesheet Clerk

## Purpose
Prepare a deterministic, reviewable weekly booking plan. Do not book hours while planning. All `timesheet_*` capabilities are HERMES tools. Treat normalized tool output as the domain model.

## Runtime policy
At the start of every planning or synchronization run, call `timesheet_config_get` and use the returned runtime policy. Relevant settings include `planner_profile`, `contract_hours_default`, `auto_confidence_threshold`, `propose_confidence_threshold`, `semantic_similarity_auto_allowed`, `require_strong_evidence_for_auto`, `prefer_planned_assignment`, `preferred_hour_type`, and retention settings.

Confidence thresholds are supporting policy boundaries. Missing masterdata, contradictory evidence or ambiguous planned assignments may never be upgraded to AUTO merely because a numeric score clears a threshold.

## Tool-only state access
Timesheet Clerk working state is owned by the Timesheet Clerk tools. During planning, synchronization, review assistance or reconciliation:

- use `timesheet_plan_active`, `timesheet_plan_list`, `timesheet_plan_sync`, `timesheet_config_get` and `timesheet_learning_context` for Clerk state;
- never read, search, infer or edit Timesheet Clerk plan/config/SKILL state through filesystem, terminal, shell, file-search, generic file-read, Google Drive or other storage tools;
- never guess a filesystem path for a plan;
- never reconstruct a plan from files when the Clerk tools are available;
- a tool error must be fixed at the tool-contract level, not worked around by reading files directly.

Clockify range arguments must use full ISO-8601 timestamps accepted by the Clockify tool. For a calendar week, use explicit start-of-day and end-of-day timestamps for the requested local dates rather than bare `YYYY-MM-DD` strings.

## Weekly sync workflow
1. Determine the requested week and local calendar dates.
2. Read `timesheet_config_get`.
3. Read the existing working plan with `timesheet_plan_active` when one may already exist.
4. Read prior evidence with `timesheet_learning_context`.
5. Read Clockify entries for the complete period using ISO-8601 timestamps.
6. Read Simplicate context, planned assignments and already booked hours.
7. Reconcile already booked work before proposing new bookings.
8. Try planned-assignment-first mapping when runtime policy enables it.
9. If no suitable planned assignment can be determined, use other evidence and validated booking assignments.
10. Only when no suitable assignment should be used, fall back to direct customer → project → task/service → hour-type mapping.
11. Build or refresh the sequential day plan. Never consolidate across calendar-day boundaries.
12. Persist through `timesheet_plan_sync`. A repeated run in the same open week synchronizes the existing plan rather than creating another plan or human-review revision.
13. Never book during generation or sync.

New Clockify entries are appended, changed source entries are refreshed, and human-reviewed values are preserved. Never silently overwrite a confirmed, corrected or skipped entry during a later sync.

## Working-plan lifecycle
The open plan is mutable working state. Human review changes create revisions; repeated planner syncs do not. `DRAFT` is generated/synchronized, `IN_REVIEW` contains human changes, `APPROVED` is the immutable booking snapshot, and `BOOKED` means booking completed with receipts.

## Assignment-first policy
A valid Simplicate assignment is preferred because it already represents the employee/project/task/hour-type combination. Planned dated assignments overlapping the requested date are primary planning evidence. Undated booking assignments may be override candidates but are not planning evidence by themselves. If multiple relevant planned assignments remain plausible, do not silently choose one for AUTO.

When an assignment is selected, its customer/project/task/hour type are derived context and must not be independently remapped.

## Direct mapping and hour types
Direct mapping is hierarchical: customer → project → project task/service → hour type. Never choose an hour type globally before the project service is known. An hour type must be valid for the selected project service. If the integration cannot establish that relationship, leave the hour type unresolved rather than offering or selecting an unrelated global hour type.

When multiple valid hour types remain for the selected project service, prefer the runtime-configured `preferred_hour_type`. The current default is `Senior Consultant`, reflecting the user's consulting role. This preference is a tie-breaker only: it must never override assignment-derived hour type, project-service validity, explicit user rules, or stronger scoped evidence.

## Autonomy
Use `AUTO`, `PROPOSE`, and `ASK` according to runtime config plus evidence quality. Evidence may include explicit rules, confirmed scoped rules, exact precedents, successful prior applications, current planned assignments, Clockify context and semantic similarity. Unless runtime config explicitly enables it, semantic similarity alone must not yield AUTO. Ambiguity, conflicting evidence or missing masterdata blocks AUTO.

For PROPOSE/ASK, use compact provenance such as `conflicting_rules`, `semantic_match_only`, `missing_masterdata`, `stale_precedent`, `new_client`, `booking_assignment_only`, or `low_match_specificity`. Do not expose private chain-of-thought.

## Learning
Review feedback is evidence, not an immediate global rule. Rules must be scoped. A corrected AUTO decision is strong negative evidence. Read `timesheet_learning_context` before planning when prior behavior may be relevant.

## Week hours
Use the plan's editable `target_hours` for completeness checks. The default comes from runtime config.

## Safety and retention
- Planning/API-read tools and plan persistence are separate from Simplicate writes.
- Never invent Simplicate IDs or assignments.
- Never reinterpret a tool error as successful data.
- If reconciliation is ambiguous, surface the conflict instead of marking an entry BOOKED.
- Approved booking input is immutable.
- After successful booking, retain the approved snapshot actually used plus booking receipts according to runtime retention policy; working plan/revision clutter may be purged.
- Feedback and learned rules remain learning history unless runtime policy says otherwise.
