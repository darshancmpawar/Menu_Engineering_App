"""Streamlit session-state helpers for authentication."""

from __future__ import annotations

import streamlit as st

from user_authentication.models import User


def init_auth_state():
    """Initialize auth keys in session state (call once at app start)."""
    if "auth_user" not in st.session_state:
        st.session_state.auth_user = None


def login_user(user: User):
    """Store authenticated user in session state."""
    st.session_state.auth_user = user


def logout_user():
    """Clear auth state."""
    st.session_state.auth_user = None


def is_authenticated() -> bool:
    return st.session_state.get("auth_user") is not None


def current_user() -> User | None:
    return st.session_state.get("auth_user")


def require_role(*roles: str) -> bool:
    """Return True if the current user has one of the given roles."""
    user = current_user()
    if user is None:
        return False
    return user.role in roles
