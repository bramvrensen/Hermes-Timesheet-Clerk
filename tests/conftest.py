import pytest


@pytest.fixture(autouse=True)
def _legacy_orchestration_tests_use_explicit_empty_snapshot(request, monkeypatch):
    """Legacy unit tests exercise orchestration mechanics, not integrations.

    0.7.9 production mapping_prepare owns a live Simplicate generation snapshot.
    These older tests intentionally remain pure/offline; dedicated 0.7.9 tests
    cover snapshot validation separately.
    """
    if request.module.__name__.split(".")[-1] not in {"test_orchestration_v06", "test_scheduling_v064"}:
        return
    import timesheet_clerk.orchestration as orchestration

    class EmptySimplicateClient:
        def __init__(self, config):
            self.config = config
        def get_context(self, start_date, end_date):
            return {}

    monkeypatch.setattr(orchestration, "SimplicateClient", EmptySimplicateClient)
    monkeypatch.setattr(orchestration, "load_generation_snapshot", lambda repo, monday, sunday: {})
