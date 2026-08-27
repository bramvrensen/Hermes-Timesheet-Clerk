"""Configuration for Timesheet Clerk integrations.

Secrets stay outside the repository. Hermes/plugin deployment supplies them as
environment variables. Streamlit may run in a sibling container/process that
shares Clerk state but not the planner profile environment; in that case we
load only the known integration variables from the configured HERMES profile
.env file. API-specific formatting belongs in the clients, never in the SKILL.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


class ConfigError(RuntimeError):
    pass


_INTEGRATION_ENV = (
    "CLOCKIFY_API_KEY",
    "CLOCKIFY_WORKSPACE_ID",
    "CLOCKIFY_USER_ID",
    "CLOCKIFY_BASE_URL",
    "SIMPLICATE_BASE_URL",
    "SIMPLICATE_API_KEY",
    "SIMPLICATE_API_SECRET",
    "SIMPLICATE_EMPLOYEE_ID",
)


def ensure_profile_integration_env(profile: str | None = None) -> None:
    """Load missing integration variables from the HERMES planner profile.

    Existing process environment always wins. This is intentionally narrow: only
    Clockify/Simplicate integration keys are imported, never arbitrary profile
    settings or provider secrets.
    """
    required_simplicate = (
        "SIMPLICATE_BASE_URL",
        "SIMPLICATE_API_KEY",
        "SIMPLICATE_API_SECRET",
        "SIMPLICATE_EMPLOYEE_ID",
    )
    if all(str(os.environ.get(key) or "").strip() for key in required_simplicate):
        return

    if profile is None:
        try:
            from .runtime import read_config
            profile = str(read_config().get("planner_profile") or "atlas")
        except Exception:
            profile = "atlas"

    profile_env = Path(
        os.environ.get("HERMES_PROFILE_ENV")
        or f"/home/hermes/.hermes/profiles/{profile}/.env"
    )
    if not profile_env.is_file():
        return

    for raw in profile_env.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in _INTEGRATION_ENV or os.environ.get(key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value


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
        ensure_profile_integration_env()
        return cls(
            base_url=_required("SIMPLICATE_BASE_URL").rstrip("/"),
            api_key=_required("SIMPLICATE_API_KEY"),
            api_secret=_required("SIMPLICATE_API_SECRET"),
            employee_id=_required("SIMPLICATE_EMPLOYEE_ID"),
        )
