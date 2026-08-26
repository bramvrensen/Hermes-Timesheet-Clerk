"""Deterministic 0.6 planner orchestration.

The LLM is allowed to decide mappings only. Clockify source fidelity, plan identity,
week metadata, revisioning, coverage, merge behaviour and persistence are owned by
Python. This module is deliberately independent from Hermes tool registration so it
can be exercised directly in tests.
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
from .storage import PlanNotFound, PlanRepository, StateConflict
from .sync import attach_source_snapshots, plan_summary, source_delta

_REVIEW_FIELDS = (
    "planned_duration_seconds",
    "planned_start",
    "planned_end",
    "booking_mode",
    "assignment",
    "direct_mapping",
    "ignored",
    "review_state",
)


def find_working_week(repo: PlanRepository, monday: str, sunday: str) -> dict[str, Any] | None:
    """Return the authoritative mutable plan for an exact week.

    Prefer the active pointer when it already points at the requested week. This
    avoids ambiguity when a safe rebuild leaves an older plan in the catalog.
    """
    try:
        active = repo.get_active()
        active_week = active.get("week") or {}
        if (
            str(active_week.get("monday") or "") == monday
            and str(active_week.get("sunday") or "") == sunday
            and active.get("status") in {"DRAFT", "IN_REVIEW"}
        ):
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


def prepare_mapping_work(
    repo: PlanRepository,
    clockify_entries: list[dict[str, Any]],
    *,
    monday: str,
    sunday: str,
    rebuild: bool = False,
) -> dict[str, Any]:
    """Build the exact mapping worklist. No LLM-authored plan payload is involved."""
    _validate_week(monday, sunday)
    existing = find_working_week(repo, monday, sunday)
    by_id = {str(row.get("id")): row for row in clockify_entries if row.get("id")}

    if rebuild or existing is None:
        required_ids = set(by_id)
        delta = source_delta(None, clockify_entries)
        mode = "REBUILD" if existing is not None else "CREATE"
    else:
        delta = source_delta(existing, clockify_entries)
        # Legacy plans without immutable source snapshots need a deterministic
        # baseline write, not a wholesale remap. Only genuinely unresolved legacy
        # entries still become mapping work.
        required_ids = set()
        if not delta.get("requires_rebaseline"):
            required_ids.update(
                str(row.get("id"))
                for key in ("new_entries", "changed_entries", "unprocessed_entries")
                for row in delta.get(key) or []
                if row.get("id")
            )
        for entry in existing.get("entries") or []:
            if is_pending_mapping(entry):
                required_ids.update(str(v) for v in entry.get("clockify_source_ids") or [] if str(v) in by_id)
        mode = "REFRESH"

    prior_by_source = _entry_by_source(existing)
    work_items = []
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
    return {
        "mode": mode,
        "week": {"monday": monday, "sunday": sunday},
        "base_plan_id": existing.get("plan_id") if existing else None,
        "base_revision": existing.get("revision") if existing else None,
        "work_count": len(work_items),
        "work_items": work_items,
        "missing_source_ids": list(delta.get("missing_source_ids") or []),
        "requires_baseline_write": requires_baseline,
        "source_delta": {
            key: delta.get(key)
            for key in ("has_changes", "requires_rebaseline", "new_count", "changed_count", "missing_count", "unprocessed_count", "unchanged_count")
        },
        "no_op": mode == "REFRESH" and not work_items and not delta.get("missing_source_ids") and not requires_baseline,
        "summary": plan_summary(existing, source_delta=delta) if existing else None,
    }


def apply_mapping_decisions(
    repo: PlanRepository,
    clockify_entries: list[dict[str, Any]],
    *,
    monday: str,
    sunday: str,
    decisions: list[dict[str, Any]],
    rebuild: bool = False,
) -> dict[str, Any]:
    """Apply mapping decisions and persist one complete, validated plan revision."""
    work = prepare_mapping_work(repo, clockify_entries, monday=monday, sunday=sunday, rebuild=rebuild)
    required_ids = {str(row["source_id"]) for row in work["work_items"]}
    decision_by_id: dict[str, dict[str, Any]] = {}
    for raw in decisions or []:
        decision = _validate_decision(raw)
        source_id = decision["source_id"]
        if source_id in decision_by_id:
            raise ContractError(f"duplicate mapping decision for Clockify source {source_id}")
        decision_by_id[source_id] = decision

    supplied_ids = set(decision_by_id)
    missing = sorted(required_ids - supplied_ids)
    extra = sorted(supplied_ids - required_ids)
    if missing:
        raise StateConflict("mapping decisions omitted required Clockify source(s): " + ", ".join(missing))
    if extra:
        raise StateConflict("mapping decisions included source(s) that are not pending work: " + ", ".join(extra))

    by_id = {str(row.get("id")): row for row in clockify_entries if row.get("id")}
    existing = find_working_week(repo, monday, sunday)
    if rebuild or existing is None:
        candidate = _build_new_plan(existing, by_id, decision_by_id, monday=monday, sunday=sunday)
        saved = repo.create(validate_plan(candidate), make_active=True)
        superseded_plan_id = None
        if rebuild and existing is not None and existing["plan_id"] != saved["plan_id"]:
            try:
                old = deepcopy(existing)
                old["status"] = "SUPERSEDED"
                repo.save_revision(old, expected_revision=int(existing["revision"]), make_active=False)
                superseded_plan_id = existing["plan_id"]
            except (StateConflict, OSError):
                # Replacement is already safely active. Failing to annotate the
                # old plan must never roll back or misreport a successful rebuild.
                superseded_plan_id = None
        return {"plan": saved, "summary": plan_summary(saved), "mode": work["mode"], "superseded_plan_id": superseded_plan_id}

    candidate = deepcopy(existing)
    candidate["status"] = "IN_REVIEW"
    candidate["source_sync_at"] = utc_now()

    missing_source_ids = set(str(v) for v in work.get("missing_source_ids") or [])
    new_entries: list[dict[str, Any]] = []
    prior_by_source = _entry_by_source(existing)

    for entry in existing.get("entries") or []:
        source_ids = [str(v) for v in entry.get("clockify_source_ids") or []]
        if any(source_id in missing_source_ids for source_id in source_ids):
            # 0.6 generated rows are one-source rows. Refuse to guess how to mutate
            # a legacy aggregate when only part of its source bundle disappeared.
            if len(source_ids) > 1 and not all(source_id in missing_source_ids for source_id in source_ids):
                raise StateConflict(
                    f"legacy consolidated entry {entry.get('entry_id')} lost only part of its Clockify sources; rebuild the week"
                )
            continue
        if any(source_id in decision_by_id for source_id in source_ids):
            continue
        new_entries.append(deepcopy(entry))

    for source_id, decision in decision_by_id.items():
        source = by_id.get(source_id)
        if source is None:
            raise StateConflict(f"Clockify source {source_id} disappeared before decisions were applied")
        prior = prior_by_source.get(source_id)
        row = _entry_from_decision(source, decision, prior=prior)
        new_entries.append(row)

    new_entries.sort(key=lambda row: (str(row.get("date") or ""), str(row.get("planned_start") or ""), str(row.get("entry_id") or "")))
    candidate["entries"] = new_entries
    candidate = attach_source_snapshots(candidate, clockify_entries)
    _assert_full_coverage(candidate, clockify_entries)
    candidate = validate_plan(candidate)
    saved = repo.save_revision(candidate, expected_revision=int(existing["revision"]), make_active=True)
    return {"plan": saved, "summary": plan_summary(saved), "mode": work["mode"]}


def _build_new_plan(
    existing: dict[str, Any] | None,
    by_id: dict[str, dict[str, Any]],
    decisions: dict[str, dict[str, Any]],
    *,
    monday: str,
    sunday: str,
) -> dict[str, Any]:
    cfg = read_config()
    target = float(existing.get("target_hours")) if existing and isinstance(existing.get("target_hours"), (int, float)) else float(cfg["contract_hours_default"])
    plan_id = f"plan-{monday}-r-{uuid.uuid4().hex[:10]}"
    plan = new_plan_skeleton(plan_id=plan_id, monday=monday, sunday=sunday, target_hours=target)
    plan["contract_hours_default"] = float(cfg["contract_hours_default"])
    rows = []
    for source_id, source in by_id.items():
        decision = decisions.get(source_id)
        if decision is None:
            raise StateConflict(f"rebuild omitted mapping decision for Clockify source {source_id}")
        rows.append(_entry_from_decision(source, decision, prior=None))
    rows.sort(key=lambda row: (str(row.get("date") or ""), str(row.get("planned_start") or ""), str(row.get("entry_id") or "")))
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
    prior_source_ids = [str(v) for v in (prior or {}).get("clockify_source_ids") or []]
    reusable_entry_id = (prior or {}).get("entry_id") if len(prior_source_ids) == 1 else None
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
        "ignored": bool(decision.get("ignored", False)),
        "mapping_state": "RESOLVED",
        "why": str(decision.get("why") or "").strip(),
        "why_not_auto": str(decision.get("why_not_auto") or "").strip(),
        "mapping_source": deepcopy(decision.get("mapping_source")),
        "confidence": decision.get("confidence"),
        "billable": bool(decision.get("billable", True)),
    }
    if decision["booking_mode"] == "assignment":
        row["assignment"] = deepcopy(decision.get("assignment") or {})
        row["direct_mapping"] = {}
    else:
        row["direct_mapping"] = deepcopy(decision.get("direct_mapping") or {})
        row["assignment"] = {}

    if prior and prior.get("review_state") in {"confirmed", "corrected", "skipped"}:
        # A legacy consolidated row can map multiple Clockify sources. Preserve its
        # reviewed booking target, but never copy aggregate duration/time into each
        # split source row.
        fields = _REVIEW_FIELDS if len(prior_source_ids) == 1 else ("booking_mode", "assignment", "direct_mapping", "ignored", "review_state")
        for field in fields:
            if field in prior:
                row[field] = deepcopy(prior[field])
        row["review_preserved_on_sync"] = True
    row["source_fingerprint"] = source_fingerprint(row)
    row["last_seen_at"] = utc_now()
    return row


def _validate_decision(raw: dict[str, Any]) -> dict[str, Any]:
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
    mode = str(result.get("booking_mode") or "").lower()
    if mode not in {"assignment", "direct"}:
        raise ContractError(f"mapping decision {source_id} has invalid booking_mode {mode!r}")
    result["booking_mode"] = mode

    ignored = bool(result.get("ignored", False))
    if not ignored and tier == "AUTO":
        if mode == "assignment":
            if not str((result.get("assignment") or {}).get("id") or "").strip():
                raise ContractError(f"AUTO decision {source_id} requires assignment.id")
        else:
            mapping = result.get("direct_mapping") or {}
            for key in ("project_id", "service_id", "hour_type_id"):
                if not str(mapping.get(key) or "").strip():
                    raise ContractError(f"AUTO decision {source_id} requires direct_mapping.{key}")
    return result


def _entry_by_source(plan: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for entry in (plan or {}).get("entries") or []:
        for source_id in entry.get("clockify_source_ids") or []:
            result[str(source_id)] = entry
    return result


def _mapping_projection(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "entry_id": entry.get("entry_id"),
        "booking_mode": entry.get("booking_mode"),
        "assignment": deepcopy(entry.get("assignment") or {}),
        "direct_mapping": deepcopy(entry.get("direct_mapping") or {}),
        "tier": entry.get("tier") or entry.get("overall_tier"),
        "why": entry.get("why"),
        "why_not_auto": entry.get("why_not_auto"),
        "review_state": entry.get("review_state"),
        "ignored": bool(entry.get("ignored", False)),
    }


def _assert_full_coverage(plan: dict[str, Any], clockify_entries: list[dict[str, Any]]) -> None:
    live = {str(row.get("id")) for row in clockify_entries if row.get("id")}
    covered = {
        str(source_id)
        for entry in plan.get("entries") or []
        for source_id in entry.get("clockify_source_ids") or []
    }
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
