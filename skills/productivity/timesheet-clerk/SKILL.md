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
- If changes exist, use only `source_delta.new_entries` and `source_delta.changed_entries` as Clockify records requiring mapping. Then read runtime config, active plan, relevant learning evidence and only the Simplicate data needed for those deltas.
- Missing source IDs must be surfaced and reconciled, never silently deleted.

## Clockify source fidelity
Every normalized Clockify row is an immutable source bundle. Keep its ID, description, client, project, tags, start, end and duration together.

- Never move source facts from one Clockify row to another.
- `clockify_source_ids`, `source.description`, `source.client`, `source.project`, source timestamps and `original_duration_seconds` must trace to the same normalized Clockify row(s).
- For a single-source entry, `original_duration_seconds` equals that row's `duration_seconds` exactly and initial planned start/end come from that row's start/end.
- Simplicate mapping may change only the booking target, never Clockify source identity or duration.
- Do not aggregate unrelated source rows merely because descriptions are similar.

## Mapping workflow when source changes exist
1. Read `timesheet_config_get`.
2. Read `timesheet_plan_active`.
3. Read `timesheet_learning_context` only when mapping decisions are required.
4. Work from the source deltas returned by `timesheet_sync_probe`, not a second full-week Clockify fetch.
5. Read Simplicate planned assignments, booking candidates and booked hours needed for changed/new rows.
6. Reconcile booked work.
7. Prefer valid planned assignments when policy allows.
8. Fall back to direct customer → project → task/service → hour type when no suitable assignment exists.
9. Persist through `timesheet_plan_sync`; repeated runs update the same open week and preserve human review.
10. Never book during generation or sync.

## Deterministic summaries
Use the summary returned by `timesheet_sync_probe`, `timesheet_plan_sync` or `timesheet_plan_summary` for all counts and totals. These values are authoritative. Do not recount ignored entries or recalculate hours in the LLM response.

## Assignment and hour-type policy
A valid Simplicate assignment is preferred. Planned dated assignments are primary planning evidence; undated booking assignments are override candidates only. Multiple plausible assignments block AUTO.

Direct mapping is hierarchical. Prefer service-scoped hour types. When Simplicate exposes no reliable service/hour-type relation, the review UI may expose global hour types as an explicit manual fallback; that fallback is never AUTO evidence. `preferred_hour_type` is only a tie-breaker among acceptable choices.

## Autonomy and learning
Use AUTO, PROPOSE and ASK according to runtime policy and evidence quality. Semantic similarity alone may not yield AUTO unless explicitly enabled. Ambiguity, conflicting evidence or missing masterdata blocks AUTO. Review feedback is evidence, not an immediate global rule; rules must be scoped.

## Lifecycle, safety and retention
The open plan is mutable working state. Human review changes create revisions; planner syncs do not. Approved booking input is immutable. Never invent Simplicate IDs, reinterpret tool errors as success, or mark ambiguous reconciliation as BOOKED. Retain approved booking snapshots and receipts according to runtime retention policy; feedback and learned rules remain long-lived learning state.
