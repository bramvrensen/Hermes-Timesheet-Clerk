"""Persistent browser authentication and shell styling for Timesheet Clerk."""

from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timedelta

import streamlit as st
from streamlit_cookies_controller import CookieController

_COOKIE_NAME = "timesheet_clerk_auth"
_THEME_COOKIE = "timesheet_clerk_theme"
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
        return str(st.context.cookies.get(name) or "")
    except Exception:
        return ""


def _theme() -> str:
    value = str(st.session_state.get("timesheet_theme") or _request_cookie(_THEME_COOKIE) or "system").lower()
    return value if value in {"system", "light", "dark"} else "system"


def _inject_shell_css() -> None:
    """Hide Streamlit chrome and apply a strong page theme before the UI renders."""
    theme = _theme()
    light = {
        "bg": "#ffffff", "surface": "#f7f8fa", "text": "#1f2328", "muted": "#667085",
        "border": "#d8dee4", "input": "#ffffff", "secondary": "#f3f4f6",
    }
    dark = {
        "bg": "#0e1117", "surface": "#161b22", "text": "#e6edf3", "muted": "#9aa4b2",
        "border": "#30363d", "input": "#161b22", "secondary": "#21262d",
    }

    def rules(p: dict[str, str]) -> str:
        return f"""
        [data-testid='stAppViewContainer'], [data-testid='stMain'], .stApp {{
            background:{p['bg']} !important; color:{p['text']} !important;
        }}
        [data-testid='stAppViewContainer'] p, [data-testid='stAppViewContainer'] span,
        [data-testid='stAppViewContainer'] label, [data-testid='stAppViewContainer'] h1,
        [data-testid='stAppViewContainer'] h2, [data-testid='stAppViewContainer'] h3 {{
            color:{p['text']};
        }}
        [data-testid='stMetric'], [data-testid='stExpander'], [data-testid='stForm'] {{
            background:{p['surface']} !important; border-color:{p['border']} !important;
        }}
        div[data-baseweb='select'] > div, div[data-baseweb='input'] > div,
        div[data-baseweb='base-input'], textarea, input {{
            background:{p['input']} !important; color:{p['text']} !important; border-color:{p['border']} !important;
        }}
        button[kind='secondary'], button[kind='tertiary'] {{
            background:{p['secondary']} !important; color:{p['text']} !important; border-color:{p['border']} !important;
        }}
        hr {{ border-color:{p['border']} !important; }}
        .stCaption, [data-testid='stCaptionContainer'] {{ color:{p['muted']} !important; }}
        """

    if theme == "dark":
        base = rules(dark)
        media = ""
    elif theme == "light":
        base = rules(light)
        media = ""
    else:
        base = rules(light)
        media = f"@media (prefers-color-scheme: dark) {{{rules(dark)}}}"

    st.markdown(
        f"""
        <style>
        [data-testid='stHeader'], [data-testid='stToolbar'], #MainMenu,
        [data-testid='stDecoration'], [data-testid='stStatusWidget'] {{ display:none !important; }}
        [data-testid='stAppViewContainer'] > .main {{ top:0 !important; }}
        .block-container {{ padding-top:0.7rem !important; max-width:1500px; }}
        {base}
        {media}
        </style>
        """,
        unsafe_allow_html=True,
    )


def require_login() -> None:
    """Require UI authentication, restored from a signed browser cookie on refresh."""
    _inject_shell_css()
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
