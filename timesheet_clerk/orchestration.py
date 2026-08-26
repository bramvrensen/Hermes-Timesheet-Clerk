"""Deterministic Timesheet Clerk planner orchestration.

HERMES decides mappings only. Python owns source fidelity, plan identity, week
metadata, coverage, revisioning, merge behaviour, scheduling and persistence.
"""
from __future__ import annotations

import os
import uuid
from copy import deepcopy
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from .contracts import ContractError, new_plan_skeleton, utc_now, validate_plan
from .coverage import is_pending_mapping
from .review import source_fingerprint
from .runtime import read_config
from .scheduling import reflow_plan_days
from .storage import PlanNotFound, PlanRepository, StateConflict
from .sync import attach_source_snapshots, covered_source_ids, plan_summary, source_delta

_REVIEW_FIELDS = (
    "planned_duration_seconds", "planned_start", "planned_end", "booking_mode",
    "assignment", "direct_mapping", "ignored", "review_state",
)
_UNKNOWN_DESCRIPTIONS = {"", "?", "??", "???", "?? -- ??", "unknown", "onbekend", "untracked"}


def find_working_week(repo: PlanRepository, monday: str, sunday: str) -> dict[str, Any] | None:
    try:
        active = repo.get_active()
        week = active.get("week") or {}
        if str(week.get("monday") or "") == monday and str(week.get("sunday") or "") == sunday and active.get("status") in {"DRAFT", "IN_REVIEW"}:
            return active
    except (PlanNotFound, KeyError, ValueError):
        pass
    matches: list[dict[str, Any]] = []
    for summary in repo.list_plans(limit=200):
        week = summary.get("week") or {}
        if str(week.get("monday") or "") != monday or str(week.get("sunday") or "") != sunday:
            continue
        try:
            plan = repo.get_latest(str(summary["plan_id"]))
        except PlanNotFound:
            continue
        if plan.get("status") in {"DRAFT", "IN_REVIEW"}:
            matches.append(plan)
    if not matches:
        return None
    matches.sort(key=lambda p: (str(p.get("updated_at") or p.get("generated_at") or ""), int(p.get("revision") or 0)))
    return matches[-1]


def prepare_mapping_work(repo: PlanRepository, clockify_entries: list[dict[str, Any]], *, monday: str, sunday: str, rebuild: bool = False) -> dict[str, Any]:
    _validate_week(monday, sunday)
    existing = find_working_week(repo, monday, sunday)
    by_id = {str(row.get("id")): row for row in clockify_entries if row.get("id")}
    live_ids = set(by_id)
    if rebuild or existing is None:
        required_ids = set(live_ids)
        delta = source_delta(None, clockify_entries)
        removed_ids: set[str] = set()
        mode = "REBUILD" if existing is not None else "CREATE"
    else:
        delta = source_delta(existing, clockify_entries)
        required_ids: set[str] = set()
        if not delta.get("requires_rebaseline"):
            required_ids.update(str(row.get("id")) for key in ("new_entries", "changed_entries", "unprocessed_entries") for row in delta.get(key) or [] if row.get("id"))
        for entry in existing.get("entries") or []:
            if is_pending_mapping(entry):
                required_ids.update(str(value) for value in entry.get("clockify_source_ids") or [] if str(value) in live_ids)
        removed_ids = covered_source_ids(existing) - live_ids
        removed_ids.update(str(value) for value in delta.get("missing_source_ids") or [])
        mode = "REFRESH"
    prior_by_source = _entry_by_source(existing)
    work_items: list[dict[str, Any]] = []
    for source_id in sorted(required_ids, key=lambda sid: str((by_id.get(sid) or {}).get("start") or sid)):
        source = by_id[source_id]
        prior = prior_by_source.get(source_id)
        work_items.append({
            "source_id": source_id,
            "source": deepcopy(source),
            "prior_mapping": _mapping_projection(prior) if prior else None,
            "human_reviewed": bool(prior and prior.get("review_state") in {"confirmed", "corrected", "skipped"}),
        })
    requires_baseline = bool(existing is not None and delta.get("requires_rebaseline"))
    removed = sorted(removed_ids)
    source_delta_summary = {key: delta.get(key) for key in ("has_changes", "requires_rebaseline", "new_count", "changed_count", "missing_count", "unprocessed_count", "unchanged_count")}
    source_delta_summary["missing_count"] = len(removed)
    source_delta_summary["has_changes"] = bool(source_delta_summary.get("has_changes") or removed)
    return {
        "mode": mode,
        "week": {"monday": monday, "sunday": sunday},
        "base_plan_id": existing.get("plan_id") if existing else None,
        "base_revision": existing.get("revision") if existing else None,
        "work_count": len(work_items),
        "work_items": work_items,
        "missing_source_ids": removed,
        "requires_baseline_write": requires_baseline,
        "source_delta": source_delta_summary,
        "no_op": mode == "REFRESH" and not work_items and not removed and not requires_baseline,
        "summary": plan_summary(existing, source_delta={**delta, "missing_count": len(removed)}) if existing else None,
    }


def apply_mapping_decisions(repo: PlanRepository, clockify_entries: list[dict[str, Any]], *, monday: str, sunday: str, decisions: list[dict[str, Any]], rebuild: bool = False) -> dict[str, Any]:
    work = prepare_mapping_work(repo, clockify_entries, monday=monday, sunday=sunday, rebuild=rebuild)
    required_ids = {str(row["source_id"]) for row in work["work_items"]}
    by_id = {str(row.get("id")): row for row in clockify_entries if row.get("id")}
    decision_by_id: dict[str, dict[str, Any]] = {}
    for raw in decisions or []:
        source_id = str((raw or {}).get("source_id") or "").strip()
        decision = _validate_decision(raw, source=by_id.get(source_id))
        source_id = decision["source_id"]
        if source_id in decision_by_id:
            raise ContractError(f"duplicate mapping decision for Clockify source {source_id}")
        decision_by_id[source_id] = decision
    missing_decisions = sorted(required_ids - set(decision_by_id))
    extra_decisions = sorted(set(decision_by_id) - required_ids)
    if missing_decisions:
        raise StateConflict("mapping decisions omitted required Clockify source(s): " + ", ".join(missing_decisions))
    if extra_decisions:
        raise StateConflict("mapping decisions included source(s) that are not pending work: " + ", ".join(extra_decisions))
    existing = find_working_week(repo, monday, sunday)
    if rebuild or existing is None:
        candidate = _build_new_plan(existing, by_id, decision_by_id, monday=monday, sunday=sunday)
        candidate = reflow_plan_days(candidate)
        saved = repo.create(validate_plan(candidate), make_active=True)
        superseded_plan_id = None
        if rebuild and existing is not None and existing["plan_id"] != saved["plan_id"]:
            try:
                old = deepcopy(existing)
                old["status"] = "SUPERSEDED"
                repo.save_revision(old, expected_revision=int(existing["revision"]), make_active=False)
                superseded_plan_id = existing["plan_id"]
            except (StateConflict, OSError):
                pass
        return {"plan": saved, "summary": plan_summary(saved), "mode": work["mode"], "superseded_plan_id": superseded_plan_id}
    candidate = deepcopy(existing)
    candidate["status"] = "IN_REVIEW"
    candidate["source_sync_at"] = utc_now()
    removed_ids = set(str(value) for value in work.get("missing_source_ids") or [])
    prior_by_source = _entry_by_source(existing)
    new_entries: list[dict[str, Any]] = []
    for entry in existing.get("entries") or []:
        source_ids = [str(value) for value in entry.get("clockify_source_ids") or [] if value]
        removed_for_entry = [source_id for source_id in source_ids if source_id in removed_ids]
        if removed_for_entry:
            if len(source_ids) > 1 and len(removed_for_entry) != len(source_ids):
                raise StateConflict("requires_explicit_rebuild: legacy consolidated entry " f"{entry.get('entry_id')} lost only part of its Clockify sources. " "Do not retry with rebuild=true automatically; an explicit user rebuild is required.")
            continue
        if any(source_id in decision_by_id for source_id in source_ids):
            continue
        new_entries.append(deepcopy(entry))
    for source_id, decision in decision_by_id.items():
        source = by_id.get(source_id)
        if source is None:
            raise StateConflict(f"Clockify source {source_id} disappeared before decisions were applied")
        new_entries.append(_entry_from_decision(source, decision, prior=prior_by_source.get(source_id)))
    candidate["entries"] = new_entries
    candidate = attach_source_snapshots(candidate, clockify_entries)
    candidate = reflow_plan_days(candidate)
    _assert_full_coverage(candidate, clockify_entries)
    saved = repo.save_revision(validate_plan(candidate), expected_revision=int(existing["revision"]), make_active=True)
    return {"plan": saved, "summary": plan_summary(saved), "mode": work["mode"]}


def _build_new_plan(existing: dict[str, Any] | None, by_id: dict[str, dict[str, Any]], decisions: dict[str, dict[str, Any]], *, monday: str, sunday: str) -> dict[str, Any]:
    cfg = read_config()
    target = float(existing["target_hours"]) if existing and isinstance(existing.get("target_hours"), (int, float)) else float(cfg["contract_hours_default"])
    plan = new_plan_skeleton(plan_id=f"plan-{monday}-r-{uuid.uuid4().hex[:10]}", monday=monday, sunday=sunday, target_hours=target)
    plan["contract_hours_default"] = float(cfg["contract_hours_default"])
    rows: list[dict[str, Any]] = []
    for source_id, source in by_id.items():
        decision = decisions.get(source_id)
        if decision is None:
            raise StateConflict(f"rebuild omitted mapping decision for Clockify source {source_id}")
        rows.append(_entry_from_decision(source, decision, prior=None))
    plan["entries"] = rows
    plan["source_sync_at"] = utc_now()
    plan = attach_source_snapshots(plan, list(by_id.values()))
    _assert_full_coverage(plan, list(by_id.values()))
    return plan


def _entry_from_decision(source: dict[str, Any], decision: dict[str, Any], *, prior: dict[str, Any] | None) -> dict[str, Any]:
    source_id = str(source["id"])
    start = source.get("start")
    end = source.get("end")
    duration = float(source.get("duration_seconds") or 0)
    prior_ids = [str(value) for value in (prior or {}).get("clockify_source_ids") or []]
    reusable_entry_id = (prior or {}).get("entry_id") if len(prior_ids) == 1 else None
    ignored = bool(decision.get("ignored", False))
    row: dict[str, Any] = {
        "entry_id": str(reusable_entry_id or f"clockify-{source_id}"),
        "clockify_source_ids": [source_id],
        "date": _local_date(start),
        "source": deepcopy(source),
        "original_duration_seconds": duration,
        "planned_duration_seconds": duration,
        "planned_start": start,
        "planned_end": end,
        "booking_mode": decision["booking_mode"],
        "tier": decision["tier"],
        "overall_tier": decision["tier"],
        "ignored": ignored,
        "mapping_state": "RESOLVED" if not (decision["tier"] == "ASK" and not _decision_target_complete(decision)) else "PENDING",
        "why": str(decision.get("why") or "").strip(),
        "why_not_auto": str(decision.get("why_not_auto") or "").strip(),
        "mapping_source": deepcopy(decision.get("mapping_source")),
        "confidence": decision.get("confidence"),
        "billable": False if ignored else bool(decision.get("billable", True)),
    }
    if ignored:
        row["booking_mode"] = "direct"
        row["direct_mapping"] = {}
        row["assignment"] = {}
    elif decision["booking_mode"] == "assignment":
        row["assignment"] = deepcopy(decision.get("assignment") or {})
        row["direct_mapping"] = {}
    else:
        row["direct_mapping"] = deepcopy(decision.get("direct_mapping") or {})
        row["assignment"] = {}
    if prior and prior.get("review_state") in {"confirmed", "corrected", "skipped"}:
        fields = _REVIEW_FIELDS if len(prior_ids) == 1 else ("booking_mode", "assignment", "direct_mapping", "ignored", "review_state")
        for field in fields:
            if field in prior:
                row[field] = deepcopy(prior[field])
        row["review_preserved_on_sync"] = True
    row["source_fingerprint"] = source_fingerprint(row)
    row["last_seen_at"] = utc_now()
    return row


def _validate_decision(raw: dict[str, Any], *, source: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ContractError("mapping decision must be an object")
    result = deepcopy(raw)
    source_id = str(result.get("source_id") or "").strip()
    if not source_id:
        raise ContractError("mapping decision.source_id is required")
    result["source_id"] = source_id
    tier = str(result.get("tier") or "").upper()
    if tier not in {"AUTO", "PROPOSE", "ASK"}:
        raise ContractError(f"mapping decision {source_id} has invalid tier {tier!r}")
    result["tier"] = tier
    ignored = bool(result.get("ignored", False))
    if ignored and _looks_unclassified(source):
        result["ignored"] = False
        result["tier"] = "ASK"
        result["booking_mode"] = "direct"
        result["direct_mapping"] = {}
        result["assignment"] = {}
        result["billable"] = True
        result["why_not_auto"] = str(result.get("why_not_auto") or "Unclassified Clockify entry requires human review.")
        return result
    if ignored:
        result["booking_mode"] = "direct"
        result["direct_mapping"] = {}
        result["assignment"] = {}
        result["billable"] = False
        return result
    mode = str(result.get("booking_mode") or "").lower()
    if mode not in {"assignment", "direct"}:
        raise ContractError(f"mapping decision {source_id} has invalid booking_mode {mode!r}")
    result["booking_mode"] = mode
    if tier == "AUTO":
        if mode == "assignment":
            if not str((result.get("assignment") or {}).get("id") or "").strip():
                raise ContractError(f"AUTO decision {source_id} requires assignment.id")
        else:
            mapping = result.get("direct_mapping") or {}
            for key in ("project_id", "service_id", "hour_type_id"):
                if not str(mapping.get(key) or "").strip():
                    raise ContractError(f"AUTO decision {source_id} requires direct_mapping.{key}")
    return result


def _looks_unclassified(source: dict[str, Any] | None) -> bool:
    if not isinstance(source, dict):
        return False
    desc = " ".join(str(source.get("description") or "").strip().casefold().split())
    no_client = not bool((source.get("client") or {}).get("id") if isinstance(source.get("client"), dict) else source.get("client"))
    no_project = not bool((source.get("project") or {}).get("id") if isinstance(source.get("project"), dict) else source.get("project"))
    return desc in _UNKNOWN_DESCRIPTIONS or (not desc and no_client and no_project)


def _decision_target_complete(decision: dict[str, Any]) -> bool:
    if decision.get("booking_mode") == "assignment":
        return bool(str((decision.get("assignment") or {}).get("id") or "").strip())
    mapping = decision.get("direct_mapping") or {}
    return all(str(mapping.get(key) or "").strip() for key in ("project_id", "service_id", "hour_type_id"))


def _entry_by_source(plan: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for entry in (plan or {}).get("entries") or []:
        for source_id in entry.get("clockify_source_ids") or []:
            result[str(source_id)] = entry
    return result


def _mapping_projection(entry: dict[str, Any]) -> dict[str, Any]:
    return {"entry_id": entry.get("entry_id"), "booking_mode": entry.get("booking_mode"), "assignment": deepcopy(entry.get("assignment") or {}), "direct_mapping": deepcopy(entry.get("direct_mapping") or {}), "tier": entry.get("tier") or entry.get("overall_tier"), "why": entry.get("why"), "why_not_auto": entry.get("why_not_auto"), "review_state": entry.get("review_state"), "ignored": bool(entry.get("ignored", False))}


def _assert_full_coverage(plan: dict[str, Any], clockify_entries: list[dict[str, Any]]) -> None:
    live = {str(row.get("id")) for row in clockify_entries if row.get("id")}
    covered = covered_source_ids(plan)
    omitted = sorted(live - covered)
    extras = sorted(covered - live)
    if omitted:
        raise StateConflict("plan does not cover live Clockify source(s): " + ", ".join(omitted))
    if extras:
        raise StateConflict("plan still references removed Clockify source(s): " + ", ".join(extras))


def _local_date(value: Any) -> str:
    text = str(value or "")
    if not text:
        raise ContractError("Clockify source start is required")
    try:
        tz = ZoneInfo(os.environ.get("TZ") or "Europe/Amsterdam")
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(tz).date().isoformat()
    except ValueError as exc:
        raise ContractError(f"invalid Clockify source start: {text!r}") from exc


def _validate_week(monday: str, sunday: str) -> None:
    start = date.fromisoformat(monday)
    end = date.fromisoformat(sunday)
    if start.weekday() != 0:
        raise ContractError("monday must be a Monday")
    if end < start:
        raise ContractError("sunday must not be before monday")
