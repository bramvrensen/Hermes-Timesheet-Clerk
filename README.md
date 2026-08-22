# HERMES Timesheet Clerk

Human-in-the-loop timesheet planning and booking for HERMES Agent.

> Status: **0.4.2 review UX stabilization.** Live Clockify/Simplicate reads, weekly sync, runtime policy, editable runtime skill, review UI, feedback, approval snapshots and retention exist. Simplicate writes remain deliberately disabled until the booking path is validated.

See [`docs/DESIGN.md`](docs/DESIGN.md) for functional design, [`docs/IMPLEMENTATION.md`](docs/IMPLEMENTATION.md) for implementation status and [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for the VPS/Compose/Caddy setup.

## 0.4.2 fixes

- entry review is isolated in Streamlit fragments so customer/project/task/hour-type filtering and review actions no longer rerender the complete page;
- skipped unresolved PROPOSE/ASK entries can be restored without being incorrectly marked as fully corrected;
- Day view resets stale date-widget state correctly and uses the selected date as a hard filter;
- week-level approve/book controls are hidden in Day view;
- scoped hour-type choices resolve their display name from Simplicate masterdata when assignment payloads expose only an ID;
- a native, theme-compatible loading indicator is shown while review context is loaded;
- the managed frontend launcher reaps adopted child processes so completed background planner runs do not accumulate as `<defunct>` zombies.

## 0.4.1 fixes

- planner sync is explicitly tool-only for Timesheet Clerk state; filesystem/file-search fallbacks are forbidden;
- Clockify range arguments are required to use full ISO-8601 timestamps;
- the live runtime SKILL receives the 0.4.1 state-access guard non-destructively on first load;
- Day view uses a real week-bounded date picker and hard-filters the selected calendar date;
- stale Streamlit elements are hidden during reruns to avoid duplicated/faded headers;
- `Generate / refresh plan` and `Refresh view` are separate actions so agent synchronization and frontend state reload are no longer conflated.

## Principles

- HERMES thinks. Mapping, evidence and autonomy belong to the planner agent plus SKILL/runtime policy.
- Streamlit reviews. It edits explicit plan state, records feedback and creates approval snapshots.
- One open working plan exists per week. Repeated planner runs sync/append instead of creating a new plan every time.
- Human review changes create revisions. Planner syncs do not create review-history noise.
- Assignment first. Direct mapping follows Customer → Project → Task/Service → Hour Type.
- Runtime config and the live `SKILL.md` are mutable state outside Git.
- Approved booking input is immutable. Writes will eventually consume only the approved snapshot.

## Shared state

The runtime is agent-independent. The default runtime state root is:

```text
/home/hermes/.hermes/timesheet-clerk
```

The old Atlas-scoped state at `/home/hermes/.hermes/profiles/atlas/timesheet-clerk` is migrated on first startup when the shared directory does not yet exist.

This allows `planner_profile` to switch from `atlas` to `atlas-worker` without moving plans, rules, config or the runtime skill.

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
```

## HERMES tools

Core tools:

```text
timesheet_config_get
timesheet_clockify_entries
timesheet_simplicate_context
timesheet_simplicate_assignments
timesheet_simplicate_booking_assignments
timesheet_simplicate_booked_hours
timesheet_plan_create
timesheet_plan_sync
timesheet_plan_active
timesheet_plan_list
timesheet_learning_context
```

`timesheet_plan_sync` is the normal repeated-run path. It creates the week plan if needed, otherwise synchronizes the open week and preserves reviewed entries.

## Runtime policy

The frontend Configuration page manages policy such as:

- planner profile;
- default contract hours;
- AUTO/PROPOSE confidence thresholds;
- strong-evidence requirements;
- planned-assignment preference;
- preferred valid direct-mapping hour type, default `Senior Consultant`;
- booked snapshot/receipt retention, default 365 days.

The planner must call `timesheet_config_get` before planning.

## Streamlit UI

The frontend provides:

- persistent login;
- week/day views;
- week-bounded date picker in Day view;
- visible planned start/end times;
- review of AUTO/PROPOSE/ASK entries;
- immediate skip/restore behaviour;
- duration edits with same-day timeline reflow;
- assignment override;
- cascading direct mapping with entry-local rerenders;
- editable runtime SKILL with automatic `/reload-skills` invocation;
- read-only state inspector for plans, revisions, mappings, rules, feedback, approvals, receipts and logs;
- separate planner sync and frontend refresh controls;
- maintenance actions including purge and managed frontend restart.

The Hour Type selector is filtered through valid service/hour-type relationships. `preferred_hour_type` is a preference only among valid choices and never overrides an assignment-derived hour type.

## Deployment

The intended steady-state deployment is a dedicated `timesheet-clerk-ui` Compose service using `frontend/managed_launcher.py`, sharing the same persistent `/home/hermes/.hermes` volume as Hermes.

The managed launcher watches the shared state for a restart request, which makes the Configuration-page `Restart frontend` button work without Docker socket access from Streamlit.

Full Compose/Caddy/update notes are in [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## Required integration configuration

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

Optional:

```text
CLOCKIFY_BASE_URL=https://api.clockify.me/api/v1
TIMESHEET_CLERK_STATE_DIR=/custom/state/path
HERMES_PROFILE_ENV=/home/hermes/.hermes/profiles/atlas/.env
```

## Retention

While a week is open, working state and required review history remain available. After successful booking, the intended retained audit artifacts are the approved snapshot actually used for booking plus booking receipts. These default to 365-day retention. Feedback and learned rules are long-lived learning state.

## Current safety boundary

Simplicate write execution is still disabled. The next write milestone is one controlled, deterministic booking from an approved snapshot, followed by idempotent day/week batching.
