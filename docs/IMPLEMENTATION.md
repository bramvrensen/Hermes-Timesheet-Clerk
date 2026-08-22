# Implementation status

`DESIGN.md` remains the functional source of truth. Deployment details live in `DEPLOYMENT.md`.

## 0.4.3

Implemented on `main`:

- native HERMES `timesheet_clerk` toolset;
- normalized Clockify and Simplicate reads;
- `timesheet_sync_probe` as the mandatory cheap first step for repeated week refreshes;
- deterministic source delta detection by Clockify source ID plus represented source facts;
- no-op fast path that stops before Simplicate/learning/full-plan context when Clockify did not change;
- `timesheet_plan_summary` plus deterministic summaries returned from probe/sync;
- Clockify source-integrity policy: ID, description, client, project, timestamps and duration stay bound to the same normalized source record;
- one open working plan per week and review preservation across planner syncs;
- human review revisions with optimistic locking;
- immutable approval snapshots and receipt primitives;
- shared agent-independent state under `/home/hermes/.hermes/timesheet-clerk`;
- editable runtime SKILL outside Git with non-destructive 0.4.1 and 0.4.3 policy migrations;
- Streamlit week/day review with functional date navigation;
- modal entry review so cascading mapping controls rerender in the dialog rather than moving the main list;
- planned-time visibility, duration edits, skip/restore, assignment override and direct mapping;
- manual global hour-type fallback when the tenant exposes no scoped service/hour-type relation; fallback is review-only and never AUTO evidence;
- live background planner-sync status persisted in `planner-sync-status.json` and refreshed in the UI;
- configurable planner profile, confidence policy, preferred hour type and 365-day booked-artifact retention;
- managed frontend launcher with restart marker and child-process reaping.

Simplicate writes remain intentionally disabled pending controlled write validation.

## Sync sequence

Existing week refresh:

```text
timesheet_sync_probe
  ├─ no source changes → deterministic summary → stop
  └─ changes → new/changed Clockify rows only
                  ↓
             mapping context
                  ↓
             timesheet_plan_sync
                  ↓
          deterministic summary
```

The planner must not refetch a full Clockify week after the probe. It reads full plan/mapping context only when source changes actually require mapping work.

## Deterministic summary fields

Current summary includes plan ID, revision, status, source-sync timestamp, clocked/workable/billable/booked/open hours, ignored count, pending-review count, entry count and source-delta counts. These values are tool-owned and must not be recomputed by the LLM.

## State

Runtime state includes:

```text
config.json
SKILL.md
active_plan.json
plans/
approvals/
receipts/
feedback_events.jsonl
rules.json
logs/
planner-sync-status.json
frontend-restart.request   # transient
```

## Remaining write milestone

Still intentionally disabled:

- Simplicate assignment/direct writes;
- one-entry controlled booking;
- idempotent day/week batch execution;
- post-booking compaction tied to confirmed receipts.

The next write validation should use one approved entry, verify exact payload/response, persist a receipt, then expand to batching.
