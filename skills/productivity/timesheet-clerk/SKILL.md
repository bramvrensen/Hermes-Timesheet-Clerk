---
name: timesheet-clerk
description: Prepare a reviewable weekly timesheet booking plan from Clockify and Simplicate. Use when planning, checking, reconciling or preparing hours for Simplicate.
---

# Timesheet Clerk 0.6

## Core contract
Timesheet Clerk owns plan structure and state. HERMES owns mapping decisions only.

Never construct, edit, serialize or infer a booking-plan JSON object. Never use terminal, execute_code, filesystem, generic file tools, Drive or guessed paths for Clerk state. Never attempt destructive recovery. If a Clerk tool fails, stop and report the exact tool error.

## Normal refresh
1. Call `timesheet_mapping_prepare` with the exact week Monday/Sunday and `rebuild=false`.
2. If `no_op=true`, stop and present the deterministic summary.
3. Otherwise process exactly the returned `work_items`. Do not map unrelated entries.
4. Read runtime config, learning context and only the Simplicate context needed to decide those work items.
5. Produce exactly one mapping decision per `source_id`.
6. Call `timesheet_mapping_apply` once with the complete decisions array and `rebuild=false`.
7. Present the deterministic summary returned by the tool.

Python owns Clockify source fidelity, source-change detection, plan/week identity, revisioning, merge behaviour, preservation of human review and persistence.

## Safe rebuild
A rebuild is allowed only after an explicit user action from the Timesheet Clerk frontend or an explicit user request.

1. Call `timesheet_mapping_prepare` for the exact week with `rebuild=true`.
2. Map every returned work item from scratch.
3. Call `timesheet_mapping_apply` once with `rebuild=true`.
4. Never delete or reset the existing plan first. The plugin creates and validates a replacement before moving the active pointer. A failed rebuild leaves the previous plan available.

## Mapping decision contract
Each decision contains:

- `source_id`: exact Clockify source ID from a work item;
- `tier`: `AUTO`, `PROPOSE` or `ASK`;
- `booking_mode`: `assignment` or `direct`;
- `assignment` when assignment mode is selected;
- `direct_mapping` when direct mode is selected;
- `ignored` when the source should not be booked;
- concise `why` and, when relevant, `why_not_auto`;
- optional `confidence`, `mapping_source` and `billable`.

Never invent IDs. AUTO requires a complete valid target. Ambiguity, conflicting evidence or missing masterdata blocks AUTO.

## Clockify source fidelity
Treat every work item's normalized Clockify source as immutable evidence. Do not copy it into plan state yourself. The plugin re-fetches Clockify at apply time and persists canonical description, client, project, tags, start, end and duration.

If a Clockify record changed, reassess the mapping decision for that source. Previously human-reviewed booking fields are preserved by Python during an incremental refresh.

## Assignment policy
Prefer valid dated Simplicate assignments when evidence supports them. A booking candidate that is not actually planned is weaker evidence. If assignment evidence is insufficient, use direct customer/project/service/hour-type mapping according to runtime policy.

Hour Type is independent from project/task filtering. Prefer the configured preferred hour type when valid, but never fabricate IDs.

## Autonomy and learning
Feedback is evidence, not an immediate global rule. Use AUTO, PROPOSE and ASK according to runtime policy, evidence quality, recency, specificity and conflicts. Semantic similarity alone may not produce AUTO unless runtime policy explicitly permits it. A corrected AUTO is strong negative evidence.

## Review and booking safety
The open plan is mutable working state. Human corrections remain authoritative on later refreshes. Approved snapshots are immutable. Never book hours while generating, refreshing or rebuilding a plan. Booking writes may only execute from an approved snapshot through the dedicated deterministic booking path.

## Updates
When asked to update Timesheet Clerk, use `timesheet_update`. Do not improvise source-code edits or update recovery from inside an active planning run.
