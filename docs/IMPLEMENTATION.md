# Implementation status

`DESIGN.md` is the functional source of truth. Deployment details live in `DEPLOYMENT.md`.

## 0.6.0 architecture cleanup

0.6.0 replaces the accumulated 0.5.x planner orchestration rather than layering another compatibility patch on top of it.

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
- safe week rebuild is create-before-switch: an existing plan remains active until a complete replacement validates and persists successfully;
- failed rebuilds do not delete or reset existing plan state;
- the destructive legacy `fresh_start_week()` path is disabled;
- missing/stale `active_plan.json` can be recovered deterministically from stored plans;
- supervised planner jobs use explicit `STARTING`, `RUNNING`, `SUCCEEDED` and `FAILED` lifecycle state with exit code and timestamps;
- a vanished planner process is reported as `FAILED`, not left indefinitely `RUNNING`;
- runtime `SKILL.md` receives a mandatory 0.6 contract guard so old live instructions cannot re-enable obsolete workflows;
- Streamlit can expose Configuration, SKILL and State even when no active plan exists;
- CI runs compile + pytest on every push to `main`, pull request and manual workflow dispatch;
- Simplicate writes remain deliberately disabled pending controlled write validation.

## 0.6 planner sequence

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
HERMES gathers only the context needed to decide mappings
      ↓
one mapping decision per source_id
      ↓
timesheet_mapping_apply(rebuild=false)
      ↓
Python re-fetches Clockify source truth
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
    "project_name": "...",
    "service_id": "...",
    "service_name": "...",
    "hour_type_id": "...",
    "hour_type_name": "...",
    "billable": true
  },
  "why": "mapping evidence",
  "confidence": 0.98
}
```

The plugin rejects incomplete AUTO mappings and decisions for source IDs that were not requested.

## Source-change behaviour

Source comparison is based on normalized Clockify facts. When an existing Clockify entry changes, for example its description:

1. `timesheet_mapping_prepare` detects the changed source;
2. HERMES receives that source as a work item;
3. `timesheet_mapping_apply` re-fetches the live source before applying decisions;
4. Python replaces the source facts in the plan;
5. a previously human-reviewed booking target remains authoritative where applicable.

This prevents the 0.5.x failure mode where stale source titles or malformed week metadata could survive because the LLM authored the complete plan payload.

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

The frontend launches a supervised Hermes planner runner rather than treating a detached PID as success state.

Expected status transitions:

```text
STARTING → RUNNING → SUCCEEDED
                   ↘ FAILED
```

Status records include a run ID, profile, timestamps and final exit code. If a status claims `RUNNING` but its runner PID no longer exists, status recovery converts it to `FAILED`.

The UI must not infer successful plan generation merely because the background process stopped. Success means the supervised runner exited successfully; plan availability is checked separately.

## Runtime SKILL migration

The live editable SKILL intentionally lives in shared runtime state and therefore survives Git updates. On plugin registration, 0.6.0 ensures a mandatory guard is present that supersedes obsolete generation/refresh instructions.

The guard requires:

1. `timesheet_mapping_prepare`;
2. exactly one mapping decision per returned work item;
3. exactly one `timesheet_mapping_apply` call;
4. no legacy plan mutation/reset tools;
5. no terminal/filesystem/code-execution recovery attempts;
6. stop and report the exact Clerk error on failure.

## Frontend behaviour

The review UI remains responsible for human review, correction, approval and future deterministic booking. It does not run mapping logic itself.

Without an active plan:

- stored plans are considered before declaring the repository empty;
- Configuration remains accessible;
- runtime SKILL remains accessible;
- State inspection remains accessible;
- a full week generation/rebuild can be launched through the supervised planner flow.

Planner status uses the 0.6 job lifecycle rather than the legacy PID-only status widget.

## Update lifecycle

The canonical repository is `bramvrensen/Hermes-Timesheet-Clerk`.

`timesheet_update` remains the intended normal update capability, but during recovery and major-version development the deterministic fallback is:

```text
docker exec -i hermes-agent sh -lc '
cd /home/hermes/.hermes/plugins/timesheet-clerk &&
git pull --ff-only &&
grep "^version:" plugin.yaml
' && \
docker restart hermes-agent timesheet-clerk-ui
```

This ensures both the Hermes plugin runtime and Streamlit frontend load the same checkout after a major code change.

## Test protection

0.6 adds regression coverage for the architectural boundaries, including:

- plan creation from decisions rather than LLM-authored plan payloads;
- changed Clockify text refresh;
- preservation of human-reviewed mappings;
- failed rebuild preserving the old active plan;
- absence of destructive/legacy tools from the manifest and plugin surface;
- supervised planner runner launch;
- dead-runner failure detection.

GitHub Actions runs `compileall` and the pytest suite on every push to `main`.

## Remaining write milestone

Still intentionally disabled:

- Simplicate assignment/direct writes;
- one-entry controlled booking;
- idempotent day/week batch execution;
- post-booking compaction tied to confirmed receipts.

The next write validation should use one approved entry, verify the exact Simplicate payload/response, persist a receipt and only then expand to batching.
