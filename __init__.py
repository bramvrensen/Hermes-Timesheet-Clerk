"""Native Hermes directory-plugin entry point for Timesheet Clerk 0.6."""

from . import plugin as _plugin
from .timesheet_clerk.runtime_v06 import ensure_v06_runtime_guard


def register(ctx):
    # Runtime SKILL state lives outside Git. Migrate its mandatory planner contract
    # before Hermes registers the skill/tools for this process.
    ensure_v06_runtime_guard(_plugin.DEFAULT_TIMESHEET_SKILL)
    return _plugin.register(ctx)


__all__ = ["register"]
