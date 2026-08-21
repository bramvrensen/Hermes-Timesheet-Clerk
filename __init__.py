"""Native Hermes directory-plugin entry point.

Hermes directory plugins are discovered through a root __init__.py containing
register(ctx). The implementation lives in plugin.py to keep the boundary
explicit and testable.
"""

from .plugin import register

__all__ = ["register"]
