# Timesheet Clerk V2: runtime boundaries

## Toolchain and model calls

`frontend/app.py` calls `timesheet_clerk.ui_planner.start_planner()`. In standalone mode it delegates to `timesheet_clerk.jobs.launch_job()`. The connection plugin uses the authenticated `POST /v1/planner/jobs` endpoint, which launches the same worker. A filesystem lease permits one generation at a time.

`jobs.generate()` reads canonical Clockify rows through `ClockifyClient`, then calls `orchestration.prepare_mapping_work()`. Python obtains Simplicate context and determines new/changed/removed sources, invalid mappings, prior human review and required decisions. An unchanged valid week stops without starting Hermes or calling a model. Simplicate context is still checked in this path so deleted/changed booking targets can be detected.

For required automatic mappings, `jobs._mapping_decisions()` writes a request unique to this job. It includes the exact work/context snapshot, numeric policy, saved instructions, feedback and rules. It starts the bundled Hermes executable with the private `timesheet-clerk` profile and only the `timesheet_clerk_planner` toolset. Hermes's provider adapter calls the OpenAI-compatible endpoint in `TIMESHEET_CLERK_MODEL_BASE_URL`, using `TIMESHEET_CLERK_MODEL` and its own model key.

The internal plugin exposes exactly two tools: `timesheet_mapping_work` reads that job's request; `timesheet_mapping_submit` accepts one decision per source ID. Hermes tool search is disabled so those tools remain directly available. Automatic session-title generation and persistent model memory are disabled. Hermes may still query provider/model metadata (the local smoke test sees an Ollama-compatible `/api/show` probe); that is not a mapping or booking LLM call. The model cannot call the old `mapping_apply`, booking tools, a shell or general filesystem tools. The process receives the model key but not Clockify/Simplicate secrets, the connector token or the web password. This restricts the model's tool surface; Hermes itself remains trusted application code, not an OS sandbox.

The server applies numeric confidence/evidence policy independently of the prompt. A claimed evidence label alone does not prove semantic correctness; model suggestions still need sensible human review and a deliberate web booking action. Python validates every supplied booking target against the captured Simplicate context, re-reads Clockify to reject changes during generation, and checks the plan revision under the state lock. It then calls `apply_mapping_decisions()` with the captured context, not a mutable global cache from a different job.

Manual import bypasses Hermes completely and supplies unresolved `ASK` decisions. All modes preserve source fidelity, coverage and revision checks.

## Deterministic core

- `clockify.py` / `simplicate.py`: direct REST clients, not MCP;
- `orchestration.py`, `sync.py`, `source.py`: source normalization, delta detection, decision validation, identity, coverage and preservation of reviewed choices;
- `scheduling.py` / `consolidation.py`: canonical daily schedule, durations, billable ordering, consolidation and reflow;
- `contracts.py`, `storage.py`, `locking.py`: validated revisions, immutable approval artifacts, feedback, rules, receipts and inter-process write coordination;
- `single_booking.py` / `booking.py`: payload construction, duplicate checks, explicit web booking, receipt and readback verification;
- `booking_attempts.py`: intent persisted before POST. Unknown/accepted outcomes block automatic retry after a crash; only an explicit 400/401/403/422 rejection allows a corrected retry. POST itself has no automatic HTTP retries.

Task/day/week web actions validate the persisted working plan and human review where required. They do not require the legacy full-week immutable approval artifact. The older `execute_booking()` path still uses an immutable approved snapshot and typed confirmation; it is not exposed by the V2 connection plugin. The standalone write switch is enforced on both canonical web booking paths.

API calls cannot book or destructively rebuild. Booking preflight and execution are serialized with state writes; concurrent edits make stale previews fail. Accepted POSTs get receipts before readback; receipt identity blocks another POST if readback fails. A process death after intent but before receipt is conservatively blocked by the separate attempt ledger. Both receipts and V2 attempts also keep Clockify source IDs, so rebuilding into a different plan does not bypass this protection. Manual reconciliation of an ambiguous attempt requires verifying Simplicate before changing the ledger; there is no automatic retry or discard button.

## Hermes dependencies and self-containment

The **internal** runtime is pinned to NousResearch/hermes-agent commit `5fc308a70719a83cccdbba4c0e39c23f5a8239d5` (`v2026.8.27`, package 0.20.6) with its dependency lock. Hermes requires an editable source installation; the Docker build uses `uv sync --locked --no-dev` with immutable image source. The app includes that runtime in its own image. `bootstrap.py` manages its private profile, plugin, SOUL, skill and model config under `/data/hermes`. Saved human policy lives under `/data/clerk`, outside Git.

The **external** ATLAS Hermes is optional. The root native plugin and `hermes_plugins/connection` expose only three HTTP tools. `connect-hermes.py` installs the small connection, creates a separate external profile and its skill, activates only that toolset and asks Hermes to configure its chat model. This external model interprets the user's chat request; the application's separate internal model produces mappings. A web-generated job uses only the internal model. Replacing ATLAS requires reconnecting this optional profile, not migrating Timesheet Clerk state.

`TIMESHEET_CLERK_MODE=standalone` disables legacy profile `.env` fallback, legacy state auto-moves and legacy planner launching. Deployment paths are explicit and do not infer Hermes root from the state directory. The service, Compose project and volumes are independent of ATLAS. Generic infrastructure remains shared: Docker, host, network/reverse proxy, external APIs and a reachable model provider.

Old compatibility modules (`plugin.py`, `job_runner.py`, historical runtime guards) remain for existing core tests/reference. The V2 native root entry point is the connection plugin. The standalone frontend is routed to the V2 worker and cannot invoke the legacy planner or plugin-update path.

## Lifecycle and validation

The installer downloads an immutable GitHub revision, preserves a private `.env`, stages code releases and waits for both HTTP services. Migration validates before replacing destination files and journals an interrupted import. It refuses a non-empty destination. Job status is persistent per job; a container restart marks interrupted workers failed without changing the existing plan.

Unit tests exercise private bootstrap, manual/unchanged paths without a model, concurrent source/review changes, the generation lease, API authentication and restricted actions, migration preservation/resume/path rejection, installer settings/update behavior and booking retry guards. `tests/smoke_hermes_v2.py` runs the real pinned Hermes CLI with a local fake model endpoint and asserts the exact two-tool surface. GitHub also builds/starts the standalone image without ATLAS. These tests use no production credentials or live bookings.
