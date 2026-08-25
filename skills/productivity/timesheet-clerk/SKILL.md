---
name: timesheet-clerk
description: Prepare a reviewable weekly timesheet booking plan from Clockify and Simplicate. Use when planning, checking, reconciling or preparing hours for Simplicate.
---

# Timesheet Clerk

## Purpose
Prepare a deterministic, reviewable weekly booking plan. Do not book hours while planning. Treat normalized Timesheet Clerk tool output as the domain model.

## Tool-only state access
Timesheet Clerk state is owned by `timesheet_*` tools. Never read, search, infer or edit Clerk plan/config/SKILL state through filesystem, terminal, generic file tools, Drive or guessed paths. Clockify range arguments must use full ISO-8601 timestamps.

## Cheap sync fast path
For every refresh of an existing week, call `timesheet_sync_probe` first.

- If `has_changes` is false, stop immediately. Do not load Simplicate context, learning context, Clockify again or the full active plan. Report only the deterministic summary returned by the probe.
- If `source_delta.requires_rebaseline` is true, call `timesheet_source_rebaseline` for the same interval. This refreshes immutable Clockify snapshots only and preserves human review. Then probe once more. Do not interpret legacy aggregate plan fields as source changes.
- If genuine changes exist after a valid baseline, map the union of `source_delta.new_entries`, `source_delta.changed_entries` and `source_delta.unprocessed_entries`. Unprocessed entries are Clockify sources already known to the canonical baseline but not represented by any working-plan entry; they must never be treated as a no-op.
- Read runtime config, active plan, relevant learning evidence and only the Simplicate data needed for those source rows.
- Missing source IDs must be surfaced and reconciled, never silently deleted.

## Clockify source fidelity
Every normalized Clockify row is an immutable source bundle. Keep its ID, description, client, project, tags, start, end and duration together.

- Canonical source comparison uses per-Clockify-ID snapshots, independent from booking-plan aggregation.
- Plan coverage is separate from baseline state. A source can be unchanged in Clockify yet still require planning when it is not covered by any `clockify_source_ids` in the working plan.
- Never move source facts from one Clockify row to another.
- Simplicate mapping, review state, ignored state and planned duration may change booking decisions but never mutate the canonical Clockify snapshot.
- Do not aggregate unrelated source rows merely because descriptions are similar.

## Mapping workflow when source changes exist
1. Read `timesheet_config_get`.
2. Read `timesheet_plan_active`.
3. Read `timesheet_learning_context` only when mapping decisions are required.
4. Work from the source deltas returned by `timesheet_sync_probe`, not a second full-week Clockify fetch.
5. Map every unique row in `new_entries`, `changed_entries` and `unprocessed_entries`; deduplicate by Clockify source ID.
6. Read Simplicate planned assignments, booking candidates and booked hours needed for those rows.
7. Reconcile booked work.
8. Prefer valid planned assignments when policy allows.
9. Fall back to direct customer → project → task/service → hour type when no suitable assignment exists.
10. Persist through `timesheet_plan_sync`; repeated runs update the same open week and preserve human review.
11. Never book during generation or sync.

## Deterministic summaries
Use the summary returned by `timesheet_sync_probe`, `timesheet_plan_sync` or `timesheet_plan_summary` for all counts and totals. These values are authoritative. Do not recount ignored entries or recalculate hours in the LLM response.

## Assignment and hour-type policy
A valid Simplicate assignment is preferred. Planned dated assignments are primary planning evidence; undated booking assignments are override candidates only. Multiple plausible assignments block AUTO.

Direct mapping is hierarchical for customer → project → task/service. Hour Type is different: the review UI must expose the full Simplicate hour-type catalog independently from customer/project/task filters. Prefer the configured `preferred_hour_type` (normally `Senior Consultant`) when it is a valid available option, but never invent it and never hide alternative hour types.

## Autonomy and learning
Use AUTO, PROPOSE and ASK according to runtime policy and evidence quality. Semantic similarity alone may not yield AUTO unless explicitly enabled. Ambiguity, conflicting evidence or missing masterdata blocks AUTO. Review feedback is evidence, not an immediate global rule; rules must be scoped.

## Lifecycle, safety and retention
The open plan is mutable working state. Human review changes create bounded working revisions; planner syncs do not create revision noise. Approved booking input is immutable. Never invent Simplicate IDs, reinterpret tool errors as success, or mark ambiguous reconciliation as BOOKED. Retain approved booking snapshots and receipts according to runtime retention policy; feedback and learned rules remain long-lived learning state.

## Plugin updates
When asked to update Timesheet Clerk, use `timesheet_update`. It performs a fast-forward Git pull against the fixed plugin checkout, preserves shared state, ensures planner-profile skill discovery, and schedules Hermes' supervised in-band gateway restart so new Python tool registrations are loaded. Do not use Docker/container restart or the Streamlit frontend as the normal plugin-update path.
