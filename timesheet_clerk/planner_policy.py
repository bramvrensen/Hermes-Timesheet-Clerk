"""Enforce the numeric autonomy policy independently of model instructions."""
from __future__ import annotations

from copy import deepcopy
import math


def enforce_policy(decisions: list[dict], policy: dict) -> list[dict]:
    result = deepcopy(decisions)
    auto = float(policy.get("auto_confidence_threshold", 0.9))
    propose = float(policy.get("propose_confidence_threshold", 0.65))
    for row in result:
        try:
            confidence = float(row.get("confidence", 0))
        except (TypeError, ValueError):
            confidence = 0.0
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            confidence = 0.0
        row["confidence"] = confidence
        tier = str(row.get("tier", "ASK")).upper()
        row["tier"] = tier
        if tier == "AUTO" and confidence < auto:
            row["tier"] = "PROPOSE" if confidence >= propose else "ASK"
            row["why_not_auto"] = "Confidence is below the Timesheet Clerk AUTO threshold."
        elif tier == "PROPOSE" and confidence < propose:
            row["tier"] = "ASK"
        evidence = row.get("mapping_source")
        evidence_kind = evidence.get("evidence_kind") if isinstance(evidence, dict) else None
        strong = evidence_kind in {"human_rule", "reviewed_mapping", "exact_match", "planned_assignment"}
        if row.get("tier") == "AUTO" and policy.get("require_strong_evidence_for_auto", True) and not strong:
            if not (evidence_kind == "semantic_similarity" and policy.get("semantic_similarity_auto_allowed", False)):
                row["tier"] = "PROPOSE"
                row["why_not_auto"] = "Strong mapping evidence was not supplied."
    return result
