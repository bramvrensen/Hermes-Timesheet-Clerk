"""Administrative Streamlit panels for Timesheet Clerk."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import streamlit as st

from . import __version__
from .runtime import (
    purge_expired_artifacts,
    read_config,
    read_runtime_skill,
    reload_skills_for_profile,
    write_config,
    write_runtime_skill,
)
from .storage import PlanRepository, repair_shared_permissions


def render_config(repo: PlanRepository, default_skill: Path) -> None:
    st.subheader("Configuration")
    st.caption(f"Timesheet Clerk v{__version__}")
    cfg = read_config()
    c1, c2 = st.columns(2)
    with c1:
        planner_profile = st.text_input("Planner profile", value=str(cfg["planner_profile"]))
        contract_hours = st.number_input("Default contract hours", min_value=0.0, step=0.5, value=float(cfg["contract_hours_default"]))
        preferred_hour_type = st.text_input(
            "Preferred hour type",
            value=str(cfg.get("preferred_hour_type") or ""),
            help="Preferred valid hour type for direct mappings, e.g. Senior Consultant. The UI still shows every available hour type.",
        )
        auto_threshold = st.slider("AUTO confidence threshold", 0, 100, int(round(float(cfg["auto_confidence_threshold"]) * 100)))
        propose_threshold = st.slider("PROPOSE confidence threshold", 0, 100, int(round(float(cfg["propose_confidence_threshold"]) * 100)))
    with c2:
        prefer_planned = st.checkbox("Prefer planned assignment", value=bool(cfg["prefer_planned_assignment"]))
        require_strong = st.checkbox("Require strong evidence for AUTO", value=bool(cfg["require_strong_evidence_for_auto"]))
        semantic_auto = st.checkbox("Allow semantic similarity alone for AUTO", value=bool(cfg["semantic_similarity_auto_allowed"]))
        retention = st.number_input("Booked snapshot/receipt retention (days)", min_value=1, step=30, value=int(cfg["booked_artifact_retention_days"]))
        purge_after = st.checkbox("Purge working plan after successful booking", value=bool(cfg["purge_after_successful_booking"]))

    if propose_threshold > auto_threshold:
        st.error("PROPOSE threshold cannot exceed AUTO threshold.")
    elif st.button("Save configuration", type="primary"):
        try:
            saved = write_config({
                **cfg,
                "planner_profile": planner_profile,
                "contract_hours_default": contract_hours,
                "preferred_hour_type": preferred_hour_type,
                "auto_confidence_threshold": auto_threshold / 100.0,
                "propose_confidence_threshold": propose_threshold / 100.0,
                "prefer_planned_assignment": prefer_planned,
                "require_strong_evidence_for_auto": require_strong,
                "semantic_similarity_auto_allowed": semantic_auto,
                "booked_artifact_retention_days": int(retention),
                "purge_after_successful_booking": purge_after,
            })
            st.success(f"Saved runtime config and ensured shared SKILL discovery for planner profile {saved['planner_profile']}.")
        except Exception as exc:
            st.error(f"Configuration was not fully applied: {exc}")

    st.divider()
    st.caption("Maintenance")
    m1, m2, m3 = st.columns(3)
    with m1:
        if st.button("Purge expired booked artifacts", use_container_width=True):
            removed = purge_expired_artifacts(repo.root)
            st.success(f"Removed {removed['approvals']} approvals and {removed['receipts']} receipts.")
    with m2:
        if st.button("Compact working revisions", use_container_width=True):
            removed = repo.compact_all_working_revisions()
            st.success(f"Removed {removed} old mutable revision file(s). Latest working history is retained; approvals/feedback are untouched.")
    with m3:
        if st.button("Repair shared permissions", use_container_width=True):
            repaired = repair_shared_permissions(repo.root)
            st.success(f"Normalized {repaired['directories']} directories and {repaired['files']} files.")

    if st.button("Restart frontend", use_container_width=True):
        marker = repo.root / "frontend-restart.request"
        marker.write_text("restart\n", encoding="utf-8")
        st.success("Frontend restart requested. The managed launcher will restart Streamlit within a few seconds.")
    st.caption("Plugin updates are not driven by this frontend. Use the Hermes-native `timesheet_update` tool; frontend restart is only for Streamlit code changes.")


def render_skill(repo: PlanRepository, default_skill: Path) -> None:
    st.subheader("Runtime SKILL.md")
    st.caption(f"Live file: {repo.root / 'SKILL.md'} · stored outside Git")
    text = read_runtime_skill(default_skill)
    edited = st.text_area("SKILL.md", value=text, height=650, label_visibility="collapsed", key="runtime-skill-editor")
    if st.button("Save SKILL and reload skills", type="primary"):
        try:
            write_runtime_skill(edited, default_skill)
            profile = str(read_config().get("planner_profile") or "atlas")
            result = reload_skills_for_profile(profile)
            reload_result = result.get("reload") or {}
            total = reload_result.get("total")
            st.success(f"SKILL saved and reloaded deterministically for {profile}{f' ({total} skills)' if total is not None else ''}. No LLM call was used.")
        except Exception as exc:
            st.error(f"SKILL saved/reload failed: {exc}")


def render_state(repo: PlanRepository, selected_plan: dict[str, Any] | None, review_context: dict[str, Any] | None = None) -> None:
    st.subheader("State inspector")
    tabs = st.tabs(["Active plan", "Revisions", "Mappings", "Rules", "Feedback", "Approvals", "Receipts", "Logs"])
    with tabs[0]:
        st.json(selected_plan, expanded=False) if selected_plan else st.info("No selected plan.")
    with tabs[1]:
        if selected_plan:
            paths = repo._revision_paths(selected_plan["plan_id"])
            st.caption(f"{len(paths)} retained mutable revision file(s). Old working revisions are compacted automatically; immutable approvals and feedback are retained separately.")
            for path in reversed(paths):
                with st.expander(path.name):
                    st.code(path.read_text(encoding="utf-8"), language="json")
    with tabs[2]:
        st.json(review_context if review_context is not None else (selected_plan or {}).get("review_context") or {}, expanded=False)
    with tabs[3]:
        st.json(repo.read_rules(), expanded=False)
    with tabs[4]:
        st.json(repo.feedback(limit=500), expanded=False)
    with tabs[5]:
        _render_files(sorted(repo.approvals_dir.glob("*.json"), reverse=True))
    with tabs[6]:
        _render_files(sorted(repo.receipts_dir.glob("*.json"), reverse=True))
    with tabs[7]:
        log_dir = repo.root / "logs"
        paths = sorted(log_dir.glob("*.log"), reverse=True) if log_dir.exists() else []
        if not paths:
            st.info("No logs yet.")
        for path in paths:
            with st.expander(path.name):
                st.code(path.read_text(encoding="utf-8", errors="replace")[-20000:])


def _render_files(paths: list[Path]) -> None:
    if not paths:
        st.info("No files.")
        return
    for path in paths:
        with st.expander(path.name):
            try:
                st.json(json.loads(path.read_text(encoding="utf-8")), expanded=False)
            except Exception:
                st.code(path.read_text(encoding="utf-8", errors="replace"))
