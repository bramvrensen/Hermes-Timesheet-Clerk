---
name: timesheet-clerk
description: Prepare a reviewable weekly timesheet booking plan from Clockify and Simplicate. Use when planning, checking, reconciling or preparing hours for Simplicate.
---

# Timesheet Clerk

## Purpose
Prepare a deterministic, reviewable weekly booking plan. Do not book hours while planning. Treat normalized Timesheet Clerk tool output as the domain model.

## Tool-only state access
Timesheet Clerk state is owned by `timesheet_*` tools. Never read, search, infer or edit Clerk plan/config/SKILL state through filesystem, terminal, generic file tools, Drive or guessed paths. Clockify range arguments must use full ISO-8601 timestamps.

## Fresh Start safety
Fresh Start is a destructive frontend-only operation. It is not a planner recovery tool and is intentionally not exposed as a Hermes tool.

- Never delete, reset or recreate a working week as an error-recovery strategy during normal refresh.
- If a sync or create call fails, preserve the current working plan and report the exact tool error.
- A human may explicitly start Fresh Start from the Timesheet Clerk frontend. The frontend performs the reset first and then launches a dedicated full rebuild run.
- During such a dedicated rebuild, read the complete Clockify week, runtime config, learning context and the Simplicate context required to map the full week. Treat every current Clockify row as new input, map every row using the normal AUTO/PROPOSE/ASK policy and persist exactly one complete plan with `timesheet_plan_create`.
- Never book hours during Fresh Start.

## Refresh workflow
For every normal refresh, call `timesheet_sync_probe` first. Source-change detection and pending mapping are separate concerns.

- If `source_delta.requires_rebaseline` is true or `source_delta.unprocessed_count > 0`, call `timesheet_source_rebaseline` for the same interval. Coverage repair creates safe unresolved ASK entries and preserves existing human review.
- After probing/repair, read `timesheet_plan_active` when mapping may still be pending or when `source_delta.changed_entries` is non-empty.
- Mapping targets are: entries covering Clockify IDs present in `source_delta.changed_entries`, entries with `mapping_state: PENDING`, plus backward-compatible pre-0.5.12 ASK entries whose `why_not_auto` is exactly `Clockify source ingested; Simplicate mapping still requires resolution.`
- Pending mapping must still be processed even when `timesheet_sync_probe.has_changes` is false. A source no-op does not mean mapping is complete.
- Re-evaluate changed existing entries and map only those targets plus pending/legacy targets. Never remap unrelated existing entries.
- Read config, learning context and only the Simplicate context needed for those targets. Apply the same AUTO/PROPOSE/ASK policy used for initial plan generation.
- For changed existing entries, preserve prior human-reviewed mapping fields unless the changed Clockify facts invalidate them. The canonical Clockify source facts themselves must always refresh from the live source through `timesheet_plan_sync`.
- After each pending target has been evaluated, set `mapping_state: RESOLVED`, even if its final tier remains ASK. Replace the ingestion sentinel with the actual reason why AUTO was not possible.
- Persist via `timesheet_plan_sync`. Incremental payloads may contain only target entries; structural week/revision metadata is normalized against the stored working plan by the plugin.
- Never book during refresh. If sync fails, stop and report the exact error. Never attempt destructive recovery.

## Clockify source fidelity
Every normalized Clockify row is an immutable source bundle. Keep its ID, description, client, project, tags, start, end and duration together. Canonical source comparison uses per-Clockify-ID snapshots and is independent from booking mapping or human review.

## Assignment and hour-type policy
Prefer valid dated Simplicate assignments when policy allows. Fall back to direct customer → project → task/service → hour type when no suitable assignment exists. Multiple plausible assignments block AUTO. Hour Type is independent from project/task filtering; prefer the configured preferred hour type when valid, but never invent IDs.

## Autonomy and learning
Use AUTO, PROPOSE and ASK according to runtime policy and evidence quality. Semantic similarity alone may not yield AUTO unless explicitly enabled. Ambiguity, conflicting evidence or missing masterdata blocks AUTO. Review feedback is evidence, not an immediate global rule; rules must be scoped.

## Lifecycle, safety and retention
The open plan is mutable working state. Human review changes create bounded working revisions; planner syncs do not create revision noise. Approved booking input is immutable. Never invent Simplicate IDs, reinterpret tool errors as success, or mark ambiguous reconciliation as BOOKED.

## Plugin updates
When asked to update Timesheet Clerk, use `timesheet_update`. It performs a fast-forward Git pull, smoke tests and the supervised Hermes gateway restart. Do not use Docker/container restart or the Streamlit frontend as the normal update path.
