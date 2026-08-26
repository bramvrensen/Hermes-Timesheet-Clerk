---
name: timesheet-clerk
description: Prepare a reviewable weekly timesheet booking plan from Clockify and Simplicate. Use when planning, checking, reconciling or preparing hours for Simplicate.
---

# Timesheet Clerk 0.6.3

## Core contract
Timesheet Clerk owns plan structure and state. HERMES owns mapping decisions only.

Never construct, edit, serialize or infer a booking-plan JSON object. Never use terminal, execute_code, filesystem, generic file tools, Drive or guessed paths for Clerk state. Never attempt destructive recovery. If a Clerk tool fails, stop and report the exact tool error.

## Normal refresh
1. Call `timesheet_mapping_prepare` with the exact week Monday/Sunday and `rebuild=false`.
2. If `no_op=true`, stop and present the deterministic summary.
3. Otherwise process exactly the returned `work_items`.
4. Read runtime config, learning context and only the Simplicate context needed for those work items.
5. Produce exactly one mapping decision per `source_id`.
6. Call `timesheet_mapping_apply` once with the complete decisions array and `rebuild=false`.
7. Present the deterministic summary returned by the tool.

The rebuild flag is fixed for the entire run. A normal refresh must never retry or escalate with `rebuild=true`. Only a new explicit user action/request may start a rebuild.

## Ignored entries
When a Clockify source should intentionally not be booked, for example lunch or excluded travel time, return `ignored=true`.

For ignored decisions:
- `source_id`, `tier`, `ignored=true` and a concise `why` are sufficient;
- `booking_mode` may be omitted or blank;
- `assignment` and `direct_mapping` may be omitted;
- never invent a project, service, hour type or assignment merely to satisfy a schema;
- Python normalizes ignored rows to a non-bookable placeholder state and sets `billable=false`.

Ignored rows remain part of Clockify source coverage but are excluded from booking.

## Removed Clockify sources
A source ID referenced by the current plan but absent from the live Clockify week is treated as removed even when an older snapshot baseline no longer contains that ID.

- A normal one-source plan row whose Clockify source disappeared is removed deterministically during refresh.
- A legacy consolidated row whose entire source bundle disappeared may also be removed deterministically.
- If only part of a legacy consolidated source bundle disappeared, Python returns `requires_explicit_rebuild`.
- `requires_explicit_rebuild` is not permission for HERMES to retry with `rebuild=true`.

## Safe rebuild
A rebuild is allowed only after an explicit user action from the Timesheet Clerk frontend or an explicit user request.

1. Call `timesheet_mapping_prepare` for the exact week with `rebuild=true`.
2. Map every returned work item from scratch.
3. Call `timesheet_mapping_apply` once with `rebuild=true`.
4. Never delete or reset the existing plan first. A failed rebuild leaves the previous plan available.

## Mapping decision contract
Every decision contains an exact `source_id`, a tier (`AUTO`, `PROPOSE`, `ASK`) and mapping rationale. Bookable decisions also contain `booking_mode` plus either assignment or direct mapping. Ignored decisions follow the special contract above.

Never invent IDs. AUTO requires a complete valid target unless the entry is explicitly ignored. Ambiguity, conflicting evidence or missing masterdata blocks AUTO for bookable entries.

## Clockify source fidelity
Treat every work item's normalized Clockify source as immutable evidence. The plugin re-fetches Clockify at apply time and persists canonical description, client, project, tags, start, end and duration.

If a Clockify record changed, reassess the mapping decision for that source. Previously human-reviewed booking fields are preserved by Python during incremental refresh.

## Assignment policy
Prefer valid dated Simplicate assignments when evidence supports them. A booking candidate that is not actually planned is weaker evidence. If assignment evidence is insufficient, use direct customer/project/service/hour-type mapping according to runtime policy.

Hour Type is independent from project/task filtering. Prefer the configured preferred hour type when valid, but never fabricate IDs.

## Autonomy and learning
Feedback is evidence, not an immediate global rule. Use AUTO, PROPOSE and ASK according to runtime policy, evidence quality, recency, specificity and conflicts. Semantic similarity alone may not produce AUTO unless runtime policy explicitly permits it. A corrected AUTO is strong negative evidence.

## Review and booking safety
The open plan is mutable working state. Human corrections remain authoritative on later refreshes. Approved snapshots are immutable. Never book hours while generating, refreshing or rebuilding a plan.

## Updates
When asked to update Timesheet Clerk, use `timesheet_update`. Do not improvise source-code edits or update recovery from inside an active planning run.
