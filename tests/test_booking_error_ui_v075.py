from timesheet_clerk.http import IntegrationError
from timesheet_clerk.ui_single_booking import _safe_error_text


def test_validation_error_includes_http_status_and_details():
    exc = IntegrationError(
        "validation_error",
        "External API rejected the request",
        422,
        False,
        {"errors": {"projectservice_id": ["Invalid project service"]}},
    )
    text = _safe_error_text(exc)
    assert "HTTP 422" in text
    assert "projectservice_id" in text
    assert "Invalid project service" in text


def test_generic_exception_remains_plain_text():
    assert _safe_error_text(RuntimeError("boom")) == "boom"
