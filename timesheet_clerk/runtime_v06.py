"""Runtime SKILL migration for the 0.6 decisions-only contract."""
from __future__ import annotations

from pathlib import Path

from .runtime import ensure_runtime_skill, write_runtime_skill

_MARKER = "<!-- timesheet-clerk-runtime-guard:0.6.1 -->"
_GUARD = """
<!-- timesheet-clerk-runtime-guard:0.6.1 -->
## Mandatory Timesheet Clerk 0.6.1 planner contract
This section supersedes all earlier Timesheet Clerk generation/refresh instructions in this file.

The planner may NOT construct or submit booking-plan JSON and may NOT call legacy plan mutation/rebaseline/fresh-start workflows. `timesheet_plan_create`, `timesheet_plan_sync`, `timesheet_source_rebaseline` and `timesheet_plan_fresh_start` are obsolete/unavailable.

For every create, refresh or explicit rebuild:
1. call `timesheet_mapping_prepare` for the exact Monday/Sunday and correct `rebuild` flag;
2. if `no_op` is true, stop;
3. decide exactly one mapping decision per returned `work_item` using only required Simplicate/config/learning context;
4. call `timesheet_mapping_apply` exactly once with the complete decisions array and the SAME `rebuild` flag.

The rebuild flag is immutable for a run. A refresh started with `rebuild=false` may never retry, recover or escalate with `rebuild=true`. A rebuild requires an explicit user action/request.

Python owns plan identity, Clockify source fidelity, durations, week metadata, coverage, revisions, merging, preservation of human review, removed-source reconciliation and persistence. Never use terminal, execute_code, filesystem or generic file tools for Timesheet Clerk state. Never delete/reset state as recovery. On any Clerk tool error, stop and report the exact error.
""".strip()


def ensure_v06_runtime_guard(default_skill: Path) -> Path:
    path = ensure_runtime_skill(default_skill)
    text = path.read_text(encoding="utf-8")
    if _MARKER not in text:
        write_runtime_skill(text.rstrip() + "\n\n" + _GUARD + "\n", default_skill)
    return path
