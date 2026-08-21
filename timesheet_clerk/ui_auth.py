"""Persistent browser authentication for the Timesheet Clerk Streamlit UI."""

from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timedelta

import streamlit as st
from streamlit_cookies_controller import CookieController

_COOKIE_NAME = "timesheet_clerk_auth"
_COOKIE_TTL_DAYS = 30
_TOKEN_CONTEXT = b"timesheet-clerk-ui-auth-v1"


def _expected_password() -> str:
    return str(os.environ.get("TIMESHEET_CLERK_UI_PASSWORD") or "").strip()


def _token(password: str) -> str:
    return hmac.new(password.encode("utf-8"), _TOKEN_CONTEXT, hashlib.sha256).hexdigest()


def _controller() -> CookieController:
    return CookieController(key="timesheet-clerk-cookies")


def _request_cookie(name: str) -> str:
    try:
        cookies = st.context.cookies
        return str(cookies.get(name) or "")
    except Exception:
        return ""


def require_login() -> None:
    """Require UI authentication, restored from a signed browser cookie on refresh."""
    expected = _expected_password()
    if not expected:
        st.error("TIMESHEET_CLERK_UI_PASSWORD is not configured.")
        st.stop()

    expected_token = _token(expected)
    request_token = _request_cookie(_COOKIE_NAME)

    if st.session_state.get("timesheet_authenticated") or hmac.compare_digest(request_token, expected_token):
        st.session_state["timesheet_authenticated"] = True
        return

    controller = _controller()
    component_token = str(controller.get(_COOKIE_NAME) or "")
    if hmac.compare_digest(component_token, expected_token):
        st.session_state["timesheet_authenticated"] = True
        return

    login_placeholder = st.empty()
    with login_placeholder.container():
        st.title("Timesheet Clerk")
        with st.form("login"):
            password = st.text_input("Password", type="password")
            submit = st.form_submit_button("Log in")

        if submit and not hmac.compare_digest(password, expected):
            st.error("Incorrect password")

    if submit and hmac.compare_digest(password, expected):
        # CookieController writes through a browser component. Do not rerun here:
        # an immediate rerun can tear down the component before its JavaScript has
        # persisted the cookie. Keep this render alive, clear the login UI and let
        # the application continue in the same run.
        controller.set(
            _COOKIE_NAME,
            expected_token,
            path="/",
            expires=datetime.now() + timedelta(days=_COOKIE_TTL_DAYS),
            max_age=_COOKIE_TTL_DAYS * 24 * 60 * 60,
            secure=True,
            same_site="strict",
        )
        st.session_state["timesheet_authenticated"] = True
        login_placeholder.empty()
        return

    st.stop()


def logout() -> None:
    """Clear both Streamlit session state and the persistent browser cookie."""
    controller = _controller()
    controller.remove(_COOKIE_NAME, path="/", secure=True, same_site="strict")
    st.session_state.clear()
    st.rerun()
