from pathlib import Path


APP = Path(__file__).resolve().parents[1] / "frontend" / "app.py"
SOURCE = APP.read_text(encoding="utf-8")


def test_reviewed_propose_ask_get_neutral_ready_visual_state():
    assert 'if tier in {"PROPOSE", "ASK"} and entry.get("review_state") in _REVIEWED_STATES: return "READY"' in SOURCE
    assert '.tc-entry.ready' in SOURCE
    assert '.tc-badge.ready' in SOURCE


def test_review_queue_only_contains_unreviewed_propose_ask():
    assert 'def _pending_review_entries' in SOURCE
    assert 'in {"PROPOSE", "ASK"}' in SOURCE
    assert 'entry.get("review_state") not in _REVIEWED_STATES' in SOURCE
    assert 'queue-review-' in SOURCE
    assert '_render_review_queue(plan)' in SOURCE


def test_original_tier_is_not_mutated_for_display():
    block = SOURCE.split('def _display_status', 1)[1].split('def _install_reviewed_css', 1)[0]
    assert 'entry["tier"] =' not in block
    assert 'entry["overall_tier"] =' not in block
