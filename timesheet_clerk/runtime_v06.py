"""Runtime SKILL migration for the 0.6 decisions-only contract."""
from __future__ import annotations

from pathlib import Path

from .runtime import ensure_runtime_skill, write_runtime_skill

_MARKER = "<!-- timesheet-clerk-runtime-guard:0.6.4 -->"
_GUARD = """
<!-- timesheet-clerk-runtime-guard:0.6.4 -->
## Mandatory Timesheet Clerk 0.6.4 planner contract
This section supersedes all earlier Timesheet Clerk generation/refresh instructions in this file.

The planner may NOT construct or submit booking-plan JSON and may NOT call legacy plan mutation/rebaseline/fresh-start workflows.

For every create, refresh or explicit rebuild:
1. call `timesheet_mapping_prepare` for the exact Monday/Sunday and correct `rebuild` flag;
2. if `no_op` is true, stop;
3. decide exactly one mapping decision per returned work item;
4. for intentionally excluded work use `ignored=true` without inventing a target;
5. unknown/unclassified work is NOT ignored: blank, `?`, `??`, `?? -- ??`, unknown/onbekend entries must remain `ASK` for human classification;
6. call `timesheet_mapping_apply` exactly once with the complete decisions array and the SAME `rebuild` flag.

The rebuild flag is immutable for a run. A refresh may never escalate itself to rebuild.

Python owns plan identity, Clockify source fidelity, week metadata, coverage, revisions, merging, human-review preservation, ignored normalization, removed-source reconciliation and the canonical daily schedule. Planned work starts at 09:00, non-billable/internal entries come before billable entries and Python reflows the day after review changes. Never use terminal, execute_code, filesystem or generic file tools for Clerk state. On any Clerk tool error, stop and report the exact error.
""".strip()


def ensure_v06_runtime_guard(default_skill: Path) -> Path:
    path = ensure_runtime_skill(default_skill)
    text = path.read_text(encoding="utf-8")
    if _MARKER not in text:
        write_runtime_skill(text.rstrip() + "\n\n" + _GUARD + "\n", default_skill)
    return path
