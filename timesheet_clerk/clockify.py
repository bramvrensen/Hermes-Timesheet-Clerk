"""Clockify REST client. No mapping or autonomy logic belongs here."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .config import ClockifyConfig
from .http import request_json


class ClockifyClient:
    def __init__(self, config: ClockifyConfig):
        self.config = config

    @property
    def headers(self) -> dict[str, str]:
        return {"X-Api-Key": self.config.api_key, "Accept": "application/json"}

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return request_json(
            "GET",
            f"{self.config.base_url}/{path.lstrip('/')}",
            headers=self.headers,
            params=params,
        )

    def _paged(self, path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        page = 1
        while True:
            query = dict(params or {})
            query.update({"page": page, "page-size": 200})
            batch = self._get(path, query) or []
            if not isinstance(batch, list):
                return batch
            result.extend(batch)
            if len(batch) < 200:
                return result
            page += 1

    def get_projects(self) -> list[dict[str, Any]]:
        return self._paged(f"workspaces/{self.config.workspace_id}/projects")

    def get_clients(self) -> list[dict[str, Any]]:
        return self._paged(f"workspaces/{self.config.workspace_id}/clients")

    def get_time_entries(self, start: str, end: str) -> list[dict[str, Any]]:
        """Return normalized entries for an ISO-8601 interval.

        The agent receives stable domain fields, not Clockify transport details.
        """
        entries = self._paged(
            f"workspaces/{self.config.workspace_id}/user/{self.config.user_id}/time-entries",
            {"start": start, "end": end, "hydrated": "true"},
        )
        projects = {p.get("id"): p for p in self.get_projects()}
        clients = {c.get("id"): c for c in self.get_clients()}

        normalized: list[dict[str, Any]] = []
        for entry in entries:
            interval = entry.get("timeInterval") or {}
            project = projects.get(entry.get("projectId"), {})
            client = clients.get(project.get("clientId"), {})
            normalized.append({
                "id": entry.get("id"),
                "description": entry.get("description") or "",
                "project": {
                    "id": project.get("id"),
                    "name": project.get("name"),
                } if project else None,
                "client": {
                    "id": client.get("id"),
                    "name": client.get("name"),
                } if client else None,
                "tags": entry.get("tagIds") or [],
                "start": interval.get("start"),
                "end": interval.get("end"),
                "duration_seconds": _duration_seconds(interval.get("start"), interval.get("end")),
            })
        return normalized


def _duration_seconds(start: str | None, end: str | None) -> int | None:
    if not start or not end:
        return None
    try:
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
        return max(0, int((end_dt - start_dt).total_seconds()))
    except ValueError:
        return None
