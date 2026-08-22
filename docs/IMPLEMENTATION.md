# Implementation status

This document records concrete implementation facts. `DESIGN.md` remains the functional source of truth. Deployment details live in `DEPLOYMENT.md`.

## 0.4.0 architecture

Implemented on `main`:

- native HERMES directory plugin and `timesheet_clerk` toolset;
- Clockify and Simplicate live reads;
- planned-assignment and booking-assignment normalization;
- weekly working-plan synchronization through `timesheet_plan_sync`;
- one open working plan per week instead of one new plan per planner run;
- planner syncs mutate/append the open week without creating review-history revisions;
- human review changes create revisions and use optimistic locking;
- reviewed entries are preserved across later planner syncs;
- immediate skip/restore review state;
- same-day timeline reflow after duration edits;
- immutable approval snapshots and booking receipt storage primitives;
- append-only feedback and persisted learned rules;
- runtime policy through `timesheet_config_get`;
- editable runtime `SKILL.md` outside Git with `/reload-skills` on save;
- agent-independent shared runtime state;
- Streamlit Review / Configuration / SKILL / State sections;
- week/day views and visible planned start/end times;
- cascading direct mapping Customer → Project → Task/Service → Hour Type;
- service/hour-type filtering derived from validated Simplicate assignment relationships;
- preferred valid direct-mapping Hour Type in runtime config, default `Senior Consultant`;
- configurable planner profile, allowing later `atlas` → `atlas-worker` migration without state migration;
- 365-day default retention for booked approval snapshots/receipts;
- managed frontend launcher and admin-triggered frontend restart request.

Simplicate writes remain intentionally disabled pending controlled write validation.

## State directory

Default 0.4.0 state root:

```text
/home/hermes/.hermes/timesheet-clerk
```

It is independent of the configured planner profile. On startup, when the shared state does not yet exist, the package migrates the legacy Atlas-scoped directory:

```text
/home/hermes/.hermes/profiles/atlas/timesheet-clerk
```

An explicit `TIMESHEET_CLERK_STATE_DIR` still overrides the default.

State contains:

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
frontend-restart.request   # transient, only while restart is requested
```

## Planner/runtime policy

The planner must call `timesheet_config_get` before planning. Current configurable policy includes:

```text
planner_profile
contract_hours_default
auto_confidence_threshold
propose_confidence_threshold
semantic_similarity_auto_allowed
require_strong_evidence_for_auto
prefer_planned_assignment
preferred_hour_type
booked_artifact_retention_days
purge_after_successful_booking
```

`preferred_hour_type` is a preference only among valid direct-mapping Hour Types for the selected service. It never overrides an assignment-derived Hour Type.

## Weekly sync semantics

`timesheet_plan_sync` is the normal repeated-run persistence path.

For an existing open week it:

- appends newly discovered Clockify source entries;
- refreshes changed source context;
- preserves confirmed/corrected/skipped human review values;
- keeps the same review revision number for planner-only synchronization.

Human review changes use the revisioned storage path. Approval creates an immutable snapshot.

## Streamlit frontend

The frontend currently provides:

- password login with persistent browser cookie;
- week/day navigation;
- planned time range and duration visibility;
- AUTO/PROPOSE/ASK/BOOKED/SKIP presentation;
- immediate skip/restore action;
- duration controls including zero-hour entries;
- assignment and direct-mapping review;
- runtime configuration editor;
- editable live SKILL;
- state inspector for plans, revisions, mappings, rules, feedback, approvals, receipts and logs;
- purge action;
- frontend restart request action.

`frontend/managed_launcher.py` runs Streamlit as a child process and watches the shared state for `frontend-restart.request`. The recommended Compose service uses this launcher so the admin restart button does not need access to the Docker socket.

## Deployment

The intended deployment is a dedicated `timesheet-clerk-ui` Compose service sharing the same persistent `/home/hermes/.hermes` volume as the Hermes runtime and using:

```text
python /home/hermes/.hermes/plugins/timesheet-clerk/frontend/managed_launcher.py
```

Caddy proxies `/timesheet` to the Streamlit service. Detailed Compose/Caddy/update notes are in `docs/DEPLOYMENT.md`.

## Required integration environment

```text
CLOCKIFY_API_KEY
CLOCKIFY_WORKSPACE_ID
CLOCKIFY_USER_ID
SIMPLICATE_BASE_URL
SIMPLICATE_API_KEY
SIMPLICATE_API_SECRET
SIMPLICATE_EMPLOYEE_ID
TIMESHEET_CLERK_UI_PASSWORD
```

The standalone frontend can load missing Simplicate values from `HERMES_PROFILE_ENV`. This is currently a credential-source detail only; it does not make Timesheet Clerk state or planner ownership Atlas-specific.

## Retention

While a week is open, required working/review state remains available. After successful booking, the intended retained audit evidence is the exact approved snapshot used for booking plus booking receipts. Default retention is 365 days. Feedback and learned rules remain long-lived learning state.

## Remaining write milestone

Still intentionally not enabled:

- Simplicate assignment/direct write capabilities;
- deterministic one-entry controlled booking;
- idempotent day/week batch execution;
- post-booking compaction tied to confirmed receipts.

The next write validation should start with one approved entry, verify the exact Simplicate payload/response, persist a receipt, then expand to day/week batching.
