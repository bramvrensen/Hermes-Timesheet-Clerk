"""Configuration for Timesheet Clerk integrations.

Secrets stay outside the repository. Hermes/plugin deployment supplies them as
environment variables. API-specific formatting belongs in the clients, never
in the SKILL.
"""

from __future__ import annotations

from dataclasses import dataclass
import os


class ConfigError(RuntimeError):
    pass


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigError(f"Missing required environment variable: {name}")
    return value


@dataclass(frozen=True)
class ClockifyConfig:
    api_key: str
    workspace_id: str
    user_id: str
    base_url: str = "https://api.clockify.me/api/v1"

    @classmethod
    def from_env(cls) -> "ClockifyConfig":
        return cls(
            api_key=_required("CLOCKIFY_API_KEY"),
            workspace_id=_required("CLOCKIFY_WORKSPACE_ID"),
            user_id=_required("CLOCKIFY_USER_ID"),
            base_url=os.getenv("CLOCKIFY_BASE_URL", cls.base_url).rstrip("/"),
        )


@dataclass(frozen=True)
class SimplicateConfig:
    base_url: str
    api_key: str
    api_secret: str
    employee_id: str

    @classmethod
    def from_env(cls) -> "SimplicateConfig":
        return cls(
            base_url=_required("SIMPLICATE_BASE_URL").rstrip("/"),
            api_key=_required("SIMPLICATE_API_KEY"),
            api_secret=_required("SIMPLICATE_API_SECRET"),
            employee_id=_required("SIMPLICATE_EMPLOYEE_ID"),
        )
