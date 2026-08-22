"""Native Hermes directory-plugin entry point.

Hermes directory plugins are discovered through a root __init__.py containing
register(ctx). The implementation lives in plugin.py; update lifecycle policy is
bound separately so it can evolve without duplicating the full plugin module.
"""

from . import plugin as _plugin
from .timesheet_clerk.update_lifecycle import build_update_handler

_plugin.handle_update = build_update_handler(_plugin)
register = _plugin.register

__all__ = ["register"]
