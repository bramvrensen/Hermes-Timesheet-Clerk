# Implementation status

`DESIGN.md` remains the functional source of truth. Deployment details live in `DEPLOYMENT.md`.

## 0.4.4

Implemented on `main`:

- native HERMES `timesheet_clerk` toolset;
- normalized Clockify and Simplicate reads;
- `timesheet_sync_probe` as the mandatory cheap first step for repeated week refreshes;
- immutable `clockify_source_snapshots` keyed per Clockify ID, independent from aggregate booking entries;
- explicit `requires_rebaseline` for legacy plans instead of guessing source changes from aggregate fields;
- deterministic `timesheet_source_rebaseline` that refreshes source truth while preserving human review decisions;
- no-op fast path that stops before Simplicate/learning/full-plan context when Clockify did not change;
- `timesheet_plan_summary` plus deterministic summaries returned from probe/sync;
- one open working plan per week and review preservation across planner syncs;
- bounded human-review working revisions with optimistic locking, plus durable feedback and immutable approval snapshots;
- shared agent-independent state under `/home/hermes/.hermes/timesheet-clerk` with ownership/mode normalization for Hermes agents and the optional UI;
- profile-safe runtime SKILL discovery through `skills.external_dirs` for the configured planner profile;
- editable runtime SKILL outside Git with real deterministic Hermes skill reload rather than an LLM `/reload-skills` prompt;
- Streamlit week/day review with functional date navigation and modal entry editing;
- planned-time visibility, duration edits, skip/restore, assignment override and direct mapping;
- Hour Type selection from the complete Simplicate hour-type catalog, independent from customer/project/task filters, with configured preference ordering;
- incomplete PROPOSE/ASK entries remain unresolved after partial edits and therefore no longer trigger resolved-target contract errors;
- live background planner-sync status persisted in `planner-sync-status.json` and refreshed in the UI;
- configurable planner profile, confidence policy, preferred hour type and booked-artifact retention;
- managed frontend launcher with restart marker and child-process reaping;
- `timesheet_update`: fast-forward Git update, compile/test smoke check and Hermes-native supervised gateway restart, independent from Streamlit and Docker restart;
- canonical deployment smoke-test documentation plus GitHub Actions compile/test workflow.

Simplicate writes remain intentionally disabled pending controlled write validation.

## Sync sequence

Existing week refresh:

```text
timesheet_sync_probe
  ├─ requires_rebaseline → timesheet_source_rebaseline → probe again
  ├─ no source changes   → deterministic summary → stop
  └─ genuine changes     → new/changed Clockify rows only
                              ↓
                         mapping context
                              ↓
                         timesheet_plan_sync
                              ↓
                    refreshed source baseline
                              ↓
                    deterministic summary
```

The planner must not refetch a full Clockify week after a valid no-op probe. A real plan sync refreshes canonical source snapshots deterministically inside Timesheet Clerk.

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

`plans/` contains bounded mutable working history. Approval snapshots, receipts and feedback are separate durable artifacts.

## Update lifecycle

From 0.4.4 onward the normal update is:

```text
timesheet_update
  ↓
git pull --ff-only
  ↓
compileall + pytest smoke test
  ↓
ensure shared SKILL/profile wiring
  ↓
Hermes supervised in-band gateway restart
  ↓
fresh process loads new Python plugin/tool registry
```

This intentionally avoids ad-hoc in-process `importlib.reload`, frontend-driven deployment and Docker/container restart.

## Remaining write milestone

Still intentionally disabled:

- Simplicate assignment/direct writes;
- one-entry controlled booking;
- idempotent day/week batch execution;
- post-booking compaction tied to confirmed receipts.

The next write validation should use one approved entry, verify exact payload/response, persist a receipt, then expand to batching.
