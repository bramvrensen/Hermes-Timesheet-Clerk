# Implementation status

`DESIGN.md` is the functional source of truth. Deployment details live in `DEPLOYMENT.md`.

## 0.6.3 ignored-entry normalization

0.6.3 fixes a planner loop where ignored Clockify rows such as lunch or excluded travel were still forced through the normal booking-target contract.

The production failures were:

```text
mapping decision <source_id> has invalid booking_mode ''
entries[n].direct_mapping.project_id is required for a resolved direct entry
```

The decision contract now distinguishes source coverage from bookability:

- every live Clockify source still produces exactly one plan row;
- `ignored=true` means the row is intentionally not bookable to Simplicate;
- HERMES may omit `booking_mode`, `assignment` and `direct_mapping` for ignored decisions;
- Python normalizes ignored rows to `booking_mode=direct`, empty mapping targets and `billable=false`;
- plan validation does not require assignment/project/service/hour-type targets for ignored rows;
- HERMES must never invent a Simplicate target merely to satisfy schema validation.

Regression tests cover both an omitted `booking_mode` and an explicitly serialized empty-string `booking_mode` for ignored entries.

## 0.6.2 current-week state selection

0.6.2 fixes the frontend case where a historical plan exists but the current calendar week does not.

The active plan pointer is intentionally not treated as proof that the current week exists. The frontend asks the plan catalog whether an exact working week exists.

Behaviour:

- an older active week remains reviewable;
- if the current Monday/Sunday has no `DRAFT` or `IN_REVIEW` plan, the Review tab shows `Generate current week`;
- current-week generation starts with `rebuild=false`;
- because no working plan exists for that exact week, `timesheet_mapping_prepare` selects CREATE mode;
- historical plans are not rebuilt, superseded or deleted;
- detection is independent from `active_plan.json`.

## 0.6.1 removed-source reconciliation

Removed Clockify detection is based on actual plan coverage versus live Clockify IDs, not snapshot history alone.

- a normal single-source row whose source disappeared is removed deterministically;
- a legacy consolidated row whose complete source bundle disappeared is removed deterministically;
- partial loss of a legacy consolidated bundle returns `requires_explicit_rebuild`;
- a refresh may never autonomously escalate to rebuild.

## 0.6 architecture cleanup

0.6 replaced LLM-authored plan payloads with a decisions-only planner contract.

Implemented on `main`:

- `timesheet_mapping_prepare` computes CREATE / REFRESH / REBUILD work from live Clockify and existing state;
- `timesheet_mapping_apply` accepts mapping decisions only and deterministically builds or merges the complete plan;
- Clockify descriptions, timestamps, durations, IDs and week metadata are Python-owned;
- complete live-source coverage is validated before persistence;
- human-reviewed mappings are preserved during incremental refresh;
- rebuild is create-before-switch;
- missing active pointers can be recovered from stored plans;
- supervised planner jobs use explicit lifecycle state;
- runtime SKILL receives a mandatory versioned guard;
- CI runs compile + pytest on every push to `main`.

## Planner sequence

```text
live Clockify week
      ↓
timesheet_mapping_prepare(rebuild=false)
      ↓
exact work_items
      ↓
HERMES mapping decisions only
      ↓
timesheet_mapping_apply(rebuild=false)
      ↓
Python source reconciliation + ignored normalization
      ↓
coverage + schema validation
      ↓
persist one working revision
```

A safe rebuild uses the same sequence with `rebuild=true` after explicit user intent. There is no delete-first phase.

## Responsibility boundary

HERMES owns interpretation, mapping choice, autonomy tier and rationale. Python owns plan identity, revisioning, week boundaries, Clockify source truth, durations, ignored normalization, removed-source reconciliation, merge behaviour, coverage/schema validation, persistence and active-plan switching.

HERMES must never use terminal, `execute_code`, filesystem manipulation or generic file tools to repair Timesheet Clerk state.

## State and recovery

Production state remains outside the Git checkout under:

```text
/home/hermes/.hermes/timesheet-clerk
```

Important artifacts include `config.json`, `SKILL.md`, `active_plan.json`, `plans/`, `approvals/`, `receipts/`, feedback/rules, logs and planner status.

## Planner job lifecycle

Expected status transitions:

```text
STARTING → RUNNING → SUCCEEDED
                   ↘ FAILED
```

A vanished runner is converted to `FAILED` instead of remaining indefinitely `RUNNING`.

## Runtime SKILL migration

The editable runtime SKILL lives in shared state and survives Git updates. The 0.6.3 guard requires prepare/apply with an immutable rebuild flag, explicitly permits target-free ignored decisions, forbids legacy mutation/reset tools and forbids terminal/filesystem/code-execution recovery.

## Update lifecycle

The canonical repository is `bramvrensen/Hermes-Timesheet-Clerk`.

During recovery or major-version development the deterministic fallback is:

```text
docker exec -i hermes-agent sh -lc '
cd /home/hermes/.hermes/plugins/timesheet-clerk &&
git pull --ff-only &&
grep "^version:" plugin.yaml
' && \
docker restart hermes-agent timesheet-clerk-ui
```

## Test protection

Regression coverage includes decisions-only plan creation, changed Clockify text, preservation of human review, safe rebuild, orphan source removal, partial aggregate loss, current-week detection, ignored decisions without booking targets, supervised planner jobs and dead-runner detection.

## Remaining write milestone

Simplicate assignment/direct writes remain intentionally disabled pending controlled write validation.
