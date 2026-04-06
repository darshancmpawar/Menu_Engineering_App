"""Streamlit session-state helpers for authentication."""

from __future__ import annotations

import streamlit as st

from user_authentication.models import User

# Keys managed by the auth system
_AUTH_KEY = "auth_user"

# Keys managed by the planner that should be cleared on logout
_PLANNER_KEYS = [
    "plan", "plan_dates", "day_types", "pool_warnings",
    "client_name", "changes_log", "view",
    "flask_started",  # keep backend running but reset UI state
]


def init_auth_state():
    """Initialize auth keys in session state (call once at app start)."""
    if _AUTH_KEY not in st.session_state:
        st.session_state[_AUTH_KEY] = None


def login_user(user: User):
    """Store authenticated user in session state."""
    st.session_state[_AUTH_KEY] = user
    # Reset view to planner on fresh login
    st.session_state["view"] = "planner"


def logout_user():
    """Clear auth state and all user-specific session data."""
    st.session_state[_AUTH_KEY] = None
    # Clear planner state so next login starts fresh
    for key in _PLANNER_KEYS:
        st.session_state.pop(key, None)


def is_authenticated() -> bool:
    return st.session_state.get(_AUTH_KEY) is not None


def current_user() -> User | None:
    return st.session_state.get(_AUTH_KEY)


def require_role(*roles: str) -> bool:
    """Return True if the current user has one of the given roles."""
    user = current_user()
    if user is None:
        return False
    return user.role in roles
