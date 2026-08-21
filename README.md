# HERMES Timesheet Clerk

Human-in-the-loop timesheet planning and booking for HERMES Agent.

The Timesheet Clerk prepares a weekly booking plan from Clockify and Simplicate context, lets the user review and correct that plan in a Streamlit UI, stores learning feedback and will ultimately book only the approved result to Simplicate.

> Status: **0.2.0 review foundation implemented.** Live reads, assignment semantics, plan persistence and the review UI exist. Simplicate writes are deliberately still disabled. [`docs/DESIGN.md`](docs/DESIGN.md) remains the functional source of truth; [`docs/IMPLEMENTATION.md`](docs/IMPLEMENTATION.md) records concrete implementation status.

## Principles

- HERMES thinks. Mapping, evidence and autonomy belong to the agent + SKILL.
- Streamlit reviews. The UI edits explicit plan state, records feedback and creates approval snapshots.
- `booking_plan.json` is the versioned contract.
- Integration code is boring. API authentication, pagination, IDs, timezone handling and API quirks stay behind the clients.
- Assignment first. Planned assignments are strong evidence; other valid booking assignments are fallback/override candidates; direct customer → project → task → hour type is the final route.
- Writes are deterministic. No integration function may silently remap an approved plan.

## Current architecture

```text
Clockify REST + Simplicate REST + permitted context
                         │
                         ▼
                 HERMES Timesheet Agent
                SKILL + feedback + rules
                         │
                         ▼
              versioned booking plan state
                         │
                         ▼
                   Streamlit UI
               review / correct / approve
                  │                 │
                  ▼                 ▼
          feedback_events.jsonl   immutable snapshot
                                      │
                                      ▼
                              future booking executor
                                      │
                                      ▼
                                  Simplicate
```

Mutable state lives under `$HERMES_HOME/timesheet-clerk` by default, not inside the Git-installed plugin directory, so plugin updates do not overwrite plans or learning history.

## HERMES tools

Integration reads:

```text
timesheet_clockify_entries
timesheet_simplicate_context
timesheet_simplicate_assignments
timesheet_simplicate_booking_assignments
timesheet_simplicate_booked_hours
```

Plan and learning state:

```text
timesheet_plan_create
timesheet_plan_active
timesheet_plan_list
timesheet_learning_context
```

`timesheet_simplicate_available_assignments` remains a deprecated compatibility alias and `timesheet_simplicate_debug_assignments` is still temporary diagnostic tooling.

## Agent planning flow

The skill instructs HERMES to:

1. read learning evidence;
2. read Clockify and Simplicate context;
3. reconcile existing bookings;
4. map planned-assignment-first;
5. assign `AUTO`, `PROPOSE` or `ASK` according to evidence and SKILL policy;
6. create a new revision-1 `DRAFT` plan with `timesheet_plan_create`;
7. never book during plan generation.

A plan includes an optional normalized `review_context` for deterministic UI dropdowns. It may contain booking assignments and customer/project/service/hour-type masterdata. This is review data, not reasoning.

## Streamlit review UI

The UI currently supports:

- own password login;
- target week hours, defaulting to 36 hours but editable per week;
- day/entry overview and plan metrics;
- editable duration;
- assignment override with contextual labels;
- switch from assignment to direct mapping;
- direct mapping cascade using normalized review context;
- append-only feedback for confirmations/corrections/skips;
- optimistic revision checks;
- deterministic same-day timeline reflow after duration edits;
- immutable approval snapshot.

It intentionally does not yet write hours to Simplicate.

Start locally from the repository/plugin directory:

```bash
TIMESHEET_CLERK_UI_PASSWORD='choose-a-password' \
streamlit run frontend/app.py \
  --server.address 127.0.0.1 \
  --server.port 8501
```

The intended public route remains `https://<hermes-host>/timesheet` behind Caddy/login. Streamlit itself should listen only on localhost.

## Required integration configuration

```text
CLOCKIFY_API_KEY
CLOCKIFY_WORKSPACE_ID
CLOCKIFY_USER_ID
SIMPLICATE_BASE_URL
SIMPLICATE_API_KEY
SIMPLICATE_API_SECRET
SIMPLICATE_EMPLOYEE_ID
```

Optional:

```text
CLOCKIFY_BASE_URL=https://api.clockify.me/api/v1
TIMESHEET_CLERK_STATE_DIR=/custom/state/path
TIMESHEET_CLERK_UI_PASSWORD=<frontend password>
```

## Separate Hermes WebUI

When using `nesquena/hermes-webui`, configure browser chat to use the actual Hermes gateway runtime rather than the WebUI's legacy local agent runtime:

```text
HERMES_WEBUI_CHAT_BACKEND=gateway
HERMES_WEBUI_GATEWAY_BASE_URL=http://hermes-agent:8642
```

The Atlas profile must also grant the plugin to `api_server`:

```yaml
platform_toolsets:
  api_server:
    - hermes-api-server
    - timesheet_clerk
```

This keeps CLI, Discord and the external WebUI on the same ATLAS/plugin runtime.

## Learning and autonomy

Feedback is append-only evidence:

```text
feedback event → precedent → candidate rule → confirmed rule
       ▲                                      │
       └──────── success/correction feedback ─┘
```

The storage layer never promotes rules. HERMES reads feedback/rules through `timesheet_learning_context` and applies the SKILL policy. Python contains no business threshold such as `confidence >= 0.70` or `seen twice = AUTO`.

## Repository

```text
Hermes-Timesheet-Clerk/
├── plugin.yaml
├── plugin.py
├── timesheet_clerk/
│   ├── clockify.py
│   ├── simplicate.py
│   ├── contracts.py
│   ├── storage.py
│   └── review.py
├── skills/productivity/timesheet-clerk/SKILL.md
├── frontend/app.py
├── docs/
└── tests/
```

## Next milestone

Deploy 0.2.0, generate one real weekly plan, validate plan → review → feedback → approval end to end, then investigate and validate Simplicate assignment/direct write semantics with one controlled booking before enabling any write flow.

## Documentation policy

`docs/DESIGN.md` is the canonical functional/architectural specification. `docs/IMPLEMENTATION.md` records technical findings and implemented behaviour. Behaviour that exists only in chat history is undocumented and is not part of the implementation contract.
