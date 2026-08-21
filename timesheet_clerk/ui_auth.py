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


def _browser_cookie(name: str) -> str:
    """Read a cookie from the initial browser request, with component fallback.

    ``st.context.cookies`` is synchronous for the current browser session and is
    therefore the reliable source after a full page refresh. The component
    fallback remains useful inside an already-open Streamlit session after a
    cookie has just been written.
    """
    try:
        value = st.context.cookies.get(name)
        if value:
            return str(value)
    except Exception:
        pass

    try:
        return str(_controller().get(name) or "")
    except Exception:
        return ""


def require_login() -> None:
    """Require UI authentication, restored from a signed browser cookie on refresh."""
    expected = _expected_password()
    if not expected:
        st.error("TIMESHEET_CLERK_UI_PASSWORD is not configured.")
        st.stop()

    expected_token = _token(expected)
    cookie_token = _browser_cookie(_COOKIE_NAME)

    if st.session_state.get("timesheet_authenticated") or hmac.compare_digest(cookie_token, expected_token):
        st.session_state["timesheet_authenticated"] = True
        return

    st.title("Timesheet Clerk")
    with st.form("login"):
        password = st.text_input("Password", type="password")
        submit = st.form_submit_button("Log in")

    if submit:
        if hmac.compare_digest(password, expected):
            controller = _controller()
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
            st.rerun()
        st.error("Incorrect password")
    st.stop()


def logout() -> None:
    """Clear both Streamlit session state and the persistent browser cookie."""
    controller = _controller()
    controller.remove(_COOKIE_NAME, path="/", secure=True, same_site="strict")
    st.session_state.clear()
    st.rerun()
