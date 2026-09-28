"""Native Hermes plugin entry point for the independent Timesheet Clerk V2 service."""
from .hermes_plugins.connection import register

__all__ = ["register"]
