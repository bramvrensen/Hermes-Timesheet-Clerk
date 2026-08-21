"""Small deterministic HTTP layer shared by external API clients."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import time

import requests


@dataclass
class IntegrationError(RuntimeError):
    error_type: str
    message: str
    status_code: int | None = None
    retryable: bool = False
    details: Any = None

    def __str__(self) -> str:
        return self.message

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": False,
            "error_type": self.error_type,
            "message": self.message,
            "status_code": self.status_code,
            "retryable": self.retryable,
            "details": self.details,
        }


def request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
    timeout: int = 30,
    max_attempts: int = 3,
) -> Any:
    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            if attempt < max_attempts:
                time.sleep(attempt)
                continue
            raise IntegrationError(
                "network_error", str(exc), retryable=True
            ) from exc

        if response.status_code in (401, 403):
            raise IntegrationError(
                "auth_error",
                "External API authentication or authorization failed",
                response.status_code,
                False,
            )

        if response.status_code == 429 or response.status_code >= 500:
            if attempt < max_attempts:
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else attempt
                time.sleep(delay)
                continue
            raise IntegrationError(
                "rate_limit" if response.status_code == 429 else "temporary_api_error",
                response.text[:1000] or "Temporary external API error",
                response.status_code,
                True,
            )

        if response.status_code in (400, 422):
            try:
                details = response.json()
            except ValueError:
                details = response.text[:2000]
            raise IntegrationError(
                "validation_error",
                "External API rejected the request",
                response.status_code,
                False,
                details,
            )

        if not response.ok:
            raise IntegrationError(
                "api_error",
                response.text[:1000] or f"HTTP {response.status_code}",
                response.status_code,
                False,
            )

        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    raise AssertionError("unreachable")
