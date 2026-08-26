# Implementation status

`DESIGN.md` is the functional source of truth. Deployment details live in `DEPLOYMENT.md`.

## 0.6.1 removed-source reconciliation

0.6.1 is a targeted correction on top of the 0.6 decisions-only architecture.

The production failure it fixes was:

```text
plan still references removed Clockify source(s): <id>, <id>
```

The root cause was that 0.6.0 derived `missing_source_ids` only from the immutable Clockify snapshot baseline. Legacy state can contain plan-entry source IDs that are no longer represented in that baseline. Those orphaned plan references therefore survived until final coverage validation.

0.6.1 changes the invariant to:

```text
removed_source_ids = plan_covered_source_ids - live_clockify_source_ids
```

Snapshot-derived missing IDs are unioned with that set, but snapshot history is no longer the sole authority for detecting deletion.

Behaviour:

- a normal single-source row whose Clockify source disappeared is removed deterministically during refresh;
- a legacy consolidated row whose complete source bundle disappeared is removed deterministically;
- if only part of a legacy consolidated bundle disappeared, the plugin returns `requires_explicit_rebuild` instead of guessing how the old aggregate should be split;
- `requires_explicit_rebuild` explicitly states that HERMES must not retry with `rebuild=true` automatically;
- planner prompts and the runtime SKILL guard now make the `rebuild` flag immutable for the duration of a run;
- a rebuild may start only through a new explicit user action/request.

Regression tests cover both orphan-source cleanup and partial-loss consolidated entries.

## 0.6 architecture cleanup

0.6 replaces the accumulated 0.5.x planner orchestration rather than layering another compatibility patch on top of it.

Implemented on `main`:

- decisions-only planner contract: HERMES maps exact work items, Python owns booking-plan construction;
- `timesheet_mapping_prepare` computes CREATE / REFRESH / REBUILD work from live Clockify source truth and existing Clerk state;
- `timesheet_mapping_apply` accepts mapping decisions only and deterministically builds or merges the complete plan;
- legacy planner mutation tools are removed from the HERMES surface: `timesheet_plan_create`, `timesheet_plan_sync`, `timesheet_source_rebaseline` and `timesheet_plan_fresh_start`;
- `plugin_legacy.py` and runtime monkeypatching are removed;
- Clockify descriptions, timestamps, durations, IDs and week metadata are never copied from LLM-authored plan JSON;
- changed Clockify source data is re-fetched at apply time;
- complete live-source coverage is validated before persistence;
- incremental refresh preserves confirmed/corrected/skipped human review decisions;
- safe week rebuild is create-before-switch;
- failed rebuilds do not delete or reset existing plan state;
- the destructive legacy `fresh_start_week()` path is disabled;
- missing/stale `active_plan.json` can be recovered deterministically from stored plans;
- supervised planner jobs use explicit `STARTING`, `RUNNING`, `SUCCEEDED` and `FAILED` lifecycle state with exit code and timestamps;
- a vanished planner process is reported as `FAILED`, not left indefinitely `RUNNING`;
- runtime `SKILL.md` receives a mandatory versioned 0.6 guard;
- Streamlit can expose Configuration, SKILL and State even when no active plan exists;
- CI runs compile + pytest on every push to `main`, pull request and manual workflow dispatch;
- Simplicate writes remain deliberately disabled pending controlled write validation.

## Planner sequence

Normal create/refresh:

```text
live Clockify week
      ↓
timesheet_mapping_prepare(rebuild=false)
      ↓
CREATE / REFRESH / NO_OP
      ↓
exact work_items only
      ↓
HERMES gathers only context needed for mapping
      ↓
one mapping decision per source_id
      ↓
timesheet_mapping_apply(rebuild=false)
      ↓
Python re-fetches Clockify source truth
      ↓
reconcile removed sources
      ↓
build / merge / coverage validation / schema validation
      ↓
one persisted working revision
```

If `no_op=true`, the planner stops without inventing additional work.

Explicit safe rebuild:

```text
timesheet_mapping_prepare(rebuild=true)
      ↓
all live Clockify rows become work_items
      ↓
HERMES returns one decision per source_id
      ↓
timesheet_mapping_apply(rebuild=true)
      ↓
build complete candidate plan in Python
      ↓
validate full Clockify coverage + plan contract
      ↓
persist and activate replacement
      ↓
best-effort mark previous working plan SUPERSEDED
```

There is no delete-first phase. Any failure before successful replacement leaves the previous plan available.

## Responsibility boundary

### HERMES owns

- interpretation of work context;
- choosing assignment/direct mapping;
- autonomy tier (`AUTO`, `PROPOSE`, `ASK`);
- mapping rationale, confidence and mapping-source evidence.

### Python owns

- plan identity and revisioning;
- week boundaries;
- Clockify source IDs and source payloads;
- original duration and timestamps;
- source snapshots and fingerprints;
- CREATE/REFRESH/REBUILD mode;
- removed-source reconciliation;
- merge behaviour;
- preservation of reviewed mappings;
- coverage and schema validation;
- persistence and active-plan switching.

HERMES must never use terminal, `execute_code`, filesystem manipulation or generic file tools to repair Timesheet Clerk state.

## Mapping decision contract

A mapping decision identifies one Clockify `source_id` and contains policy/mapping output, not source facts. Conceptually:

```json
{
  "source_id": "clockify-id",
  "tier": "AUTO",
  "booking_mode": "direct",
  "direct_mapping": {
    "project_id": "...",
    "service_id": "...",
    "hour_type_id": "..."
  },
  "why": "mapping evidence",
  "confidence": 0.98
}
```

The plugin rejects incomplete AUTO mappings and decisions for source IDs that were not requested.

## Source-change behaviour

When an existing Clockify entry changes:

1. `timesheet_mapping_prepare` detects the changed source;
2. HERMES receives that source as a work item;
3. `timesheet_mapping_apply` re-fetches the live source;
4. Python replaces canonical source facts in the plan;
5. a previously human-reviewed booking target remains authoritative where applicable.

When a Clockify entry disappears:

1. Python compares actual plan coverage to live Clockify IDs;
2. safe removed rows are dropped without an LLM mapping decision;
3. ambiguous partial removal from a legacy aggregate fails closed with `requires_explicit_rebuild`.

## State and recovery

Production state remains outside the Git checkout under:

```text
/home/hermes/.hermes/timesheet-clerk
```

Important artifacts:

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
frontend-restart.request
```

If `active_plan.json` is missing or invalid while stored plans still exist, state selection promotes the newest stored plan instead of treating the repository as empty.

Working-plan revision retention remains bounded. Approval snapshots, receipts and feedback are separate durable artifacts.

## Planner job lifecycle

Expected status transitions:

```text
STARTING → RUNNING → SUCCEEDED
                   ↘ FAILED
```

Status records include a run ID, profile, timestamps and final exit code. A status that claims `RUNNING` while its runner PID no longer exists is converted to `FAILED`.

## Runtime SKILL migration

The editable runtime SKILL lives in shared state and survives Git updates. Plugin registration appends a mandatory versioned guard when required.

The 0.6.1 guard requires:

1. `timesheet_mapping_prepare`;
2. exactly one decision per returned work item;
3. exactly one `timesheet_mapping_apply` call;
4. the same rebuild flag for prepare and apply;
5. no escalation from `rebuild=false` to `rebuild=true` after failure;
6. no legacy mutation/reset tools;
7. no terminal/filesystem/code-execution recovery attempts;
8. stop and report the exact Clerk error on failure.

## Update lifecycle

The canonical repository is `bramvrensen/Hermes-Timesheet-Clerk`.

`timesheet_update` remains the intended normal update capability. During recovery or major-version development the deterministic fallback is:

```text
docker exec -i hermes-agent sh -lc '
cd /home/hermes/.hermes/plugins/timesheet-clerk &&
git pull --ff-only &&
grep "^version:" plugin.yaml
' && \
docker restart hermes-agent timesheet-clerk-ui
```

## Test protection

Regression coverage includes:

- plan creation from decisions rather than LLM-authored plan payloads;
- changed Clockify text refresh;
- preservation of human-reviewed mappings;
- failed rebuild preserving the old active plan;
- removal of orphaned plan source IDs even when snapshot history lost them;
- explicit-rebuild failure for partial loss of a legacy consolidated source bundle;
- absence of destructive/legacy tools from the manifest and plugin surface;
- supervised planner runner launch;
- dead-runner failure detection.

GitHub Actions runs `compileall` and pytest on every push to `main`.

## Remaining write milestone

Still intentionally disabled:

- Simplicate assignment/direct writes;
- one-entry controlled booking;
- idempotent day/week batch execution;
- post-booking compaction tied to confirmed receipts.

The next write validation should use one approved entry, verify the exact Simplicate payload/response, persist a receipt and only then expand to batching.
