# Implementation status

This document records implementation facts that are more concrete than the functional design. `DESIGN.md` remains the source of truth for intended behaviour.

## 0.2.0 review foundation

Implemented on `main`:

- native HERMES directory-plugin entrypoint and `timesheet_clerk` toolset;
- bundled skill at `skills/productivity/timesheet-clerk/SKILL.md`;
- Clockify REST reads for normalized time entries;
- Simplicate REST reads for active projects, services, hour types, planned assignments, booking assignments and booked hours;
- tenant-validated assignment normalization;
- versioned booking-plan contract validation in `timesheet_clerk/contracts.py`;
- atomic immutable-per-revision plan persistence in `timesheet_clerk/storage.py`;
- optimistic revision checking so an opened plan cannot silently overwrite a newer review revision;
- an explicit active-plan pointer stored outside the plugin install directory;
- append-only `feedback_events.jsonl` storage;
- rule storage that only persists agent-derived rules and never infers/promotes them itself;
- immutable approval snapshots;
- booking-receipt storage primitive for the later write flow;
- deterministic same-day timeline reflow after duration edits;
- Streamlit review UI with its own login, editable weekly target hours, per-entry review, assignment override, direct-mapping cascade from normalized review context, feedback capture and approval snapshot creation;
- Simplicate write execution is still intentionally disabled.

### HERMES tools

Read/integration tools:

- `timesheet_clockify_entries`
- `timesheet_simplicate_context`
- `timesheet_simplicate_assignments`
- `timesheet_simplicate_booking_assignments`
- `timesheet_simplicate_available_assignments` (deprecated compatibility alias)
- `timesheet_simplicate_debug_assignments` (temporary diagnostic)
- `timesheet_simplicate_booked_hours`

Plan/learning tools:

- `timesheet_plan_create`
- `timesheet_plan_active`
- `timesheet_plan_list`
- `timesheet_learning_context`

`timesheet_plan_create` validates and atomically stores a complete agent-produced revision-1 plan. It does not decide mappings, confidence or autonomy.

## State directory

Mutable state is never written inside the Git-installed plugin directory. Default location:

```text
$HERMES_HOME/timesheet-clerk/
├── active_plan.json
├── plans/<plan-id>/revision-0001.json
├── approvals/<plan-id>-rNNNN.json
├── feedback_events.jsonl
├── rules.json
└── receipts/
```

Override with:

```text
TIMESHEET_CLERK_STATE_DIR=/custom/path
```

This keeps plans and learning history intact across plugin updates.

## Plan contract

Current `schema_version` is `1`. New agent plans start as revision `1`, status `DRAFT`, with the 36-hour contract default and an independently editable `target_hours`.

Draft/review plans may contain intentionally unresolved targets for `ASK`/`PROPOSE` entries. `AUTO` entries must be complete. A reviewed entry must be complete before approval.

The agent should include normalized `review_context` in the plan so Streamlit can render deterministic override controls without doing mapping work itself. Recommended keys:

```text
booking_assignments
customers
projects
services
hour_types
```

No credentials, API prefixes or private chain-of-thought belong in a plan.

## Review and learning semantics

Streamlit edits one exact plan revision. A material review generates an append-only feedback event containing:

- plan/entry identity;
- source fingerprint;
- original proposal;
- reviewed values;
- changed fields;
- optional reason;
- original mapping source/tiers;
- outcome (`confirmed`, `corrected`, `skipped`).

The storage layer does not generalize feedback. HERMES reads it through `timesheet_learning_context` and applies the policy from the skill.

A duration edit may shift subsequent planned time slots on the same calendar day only. Entries on another day are never moved by this deterministic UI operation.

## Streamlit

Runtime dependency:

```text
streamlit>=1.48,<2
```

Start from the repository/plugin directory:

```bash
TIMESHEET_CLERK_UI_PASSWORD='<secret>' \
streamlit run frontend/app.py --server.address 127.0.0.1 --server.port 8501
```

The intended external route remains `/timesheet` behind Caddy/auth. Streamlit should only listen locally. Caddy configuration is deployment technology, not business logic.

The UI currently creates approval snapshots but deliberately does not execute Simplicate writes.

## Required integration environment

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
TIMESHEET_CLERK_STATE_DIR=/path
TIMESHEET_CLERK_UI_PASSWORD=<secret>
```

## Skill discovery

The skill file follows the normal Hermes category layout:

```text
skills/productivity/timesheet-clerk/SKILL.md
```

Because it is bundled by a plugin and registered through `ctx.register_skill(...)`, the runtime-qualified name remains:

```text
timesheet-clerk:timesheet-clerk
```

The skill now explicitly instructs the agent that `timesheet_*` names are tools, not skills/scripts, and forbids terminal/direct-REST fallbacks while the plugin toolset is available.

## Simplicate assignment facts validated in the live tenant

```text
employees[]                  -> assigned employees
status.is_blocked            -> blocked state
status.is_done               -> completed state
is_planned                   -> explicit planning flag
project                      -> project object
project.organization         -> customer/organization
projectservice               -> task/service
projecthourstype             -> hour type
hours_type                   -> secondary hour-type field
hours / hours_total          -> assignment hour values
```

Planned assignments require employee membership, active status, `is_planned = true`, both dates and date overlap.

Booking assignments require employee membership, active assignment/project, a project service with `use_in_resource_planner = true`, and overlap when dated. Undated candidates can be booking targets but are never planning evidence by themselves.

## Hermes/WebUI runtime finding

The separate `nesquena/hermes-webui` container initially used its own legacy agent runtime even though `HERMES_API_URL` pointed at the Hermes API server. That caused plugin-tool discovery to differ from CLI/dashboard/Discord.

The working deployment explicitly selects the Hermes gateway backend:

```text
HERMES_WEBUI_CHAT_BACKEND=gateway
HERMES_WEBUI_GATEWAY_BASE_URL=http://hermes-agent:8642
```

and the Atlas profile grants the plugin to the API platform:

```yaml
platform_toolsets:
  api_server:
    - hermes-api-server
    - timesheet_clerk
```

With this configuration CLI, Discord and the separate WebUI all execute the same native Timesheet Clerk tools.

## Validation status

Validated live:

- plugin installs and updates from GitHub;
- `timesheet_clockify_entries` returns live entries;
- planned assignments match the Simplicate planning view;
- booking assignments are recognizable and normalized correctly;
- CLI, Discord and separate WebUI can directly execute the plugin tools.

Implemented but still requiring deployment validation:

- plan creation through `timesheet_plan_create`;
- plan revision conflict handling against a live HERMES state directory;
- Streamlit review flow and login;
- append-only feedback generation;
- immutable approval snapshot.

Intentionally not implemented yet:

- Simplicate assignment/direct write capabilities;
- idempotent batch booking execution;
- controlled write activation.

## Next technical validation

1. Update the plugin to 0.2.0 and restart/reload Hermes.
2. Ask HERMES to generate one real week plan and persist it with `timesheet_plan_create`.
3. Start Streamlit locally and review that plan.
4. Confirm a correction produces a new plan revision plus one feedback event.
5. Confirm approval creates an immutable snapshot.
6. Only then validate Simplicate write semantics against a controlled live booking.
