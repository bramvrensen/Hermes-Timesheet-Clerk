"""Persist the Simplicate snapshot used between mapping prepare and apply."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .storage import PlanRepository, StateConflict


def snapshot_path(repo: PlanRepository, monday: str, sunday: str) -> Path:
    return repo.root / "cache" / f"generation-simplicate-{monday}-{sunday}.json"


def store_generation_snapshot(repo: PlanRepository, monday: str, sunday: str, context: dict[str, Any]) -> None:
    path = snapshot_path(repo, monday, sunday)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps({"monday": monday, "sunday": sunday, "context": context}, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def load_generation_snapshot(repo: PlanRepository, monday: str, sunday: str) -> dict[str, Any]:
    path = snapshot_path(repo, monday, sunday)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StateConflict("No Simplicate generation snapshot is available. Run mapping prepare again before applying decisions.") from exc
    if payload.get("monday") != monday or payload.get("sunday") != sunday or not isinstance(payload.get("context"), dict):
        raise StateConflict("Stored Simplicate generation snapshot does not match the requested week. Run mapping prepare again.")
    return payload["context"]
