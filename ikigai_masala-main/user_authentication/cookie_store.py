"""Persistent auth-token storage via a browser cookie.

``st.session_state`` is per-Streamlit-session in-memory storage — it
dies on page hard-refresh, new tab, server restart, and Streamlit-Cloud
hibernation. To keep users signed in across those events the bearer
token has to live somewhere the *browser* keeps. We use a cookie
(via extra-streamlit-components) rather than localStorage because the
cookie is sent on the very first HTTP request, avoiding the
"flash of login form" you get with a JS round-trip.

Cookie name: ``ikigai_auth``. Lifetime: 12 hours (matches the policy
agreed with the operator). The cookie value is the same signed bearer
token issued by ``POST /api/v1/auth/login``; tampering invalidates the
HMAC so the server rejects it on the next request.
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

import streamlit as st

# Lazily imported so test/script paths that don't run inside Streamlit
# (which is what test_*_helpers.py and CI imports do) don't pay the
# import cost or require the dep to be installed at all.
try:
    import extra_streamlit_components as stx
except ImportError:  # pragma: no cover — handled lazily by callers
    stx = None  # type: ignore[assignment]


_COOKIE_NAME = "ikigai_auth"
_COOKIE_TTL_HOURS = 12
# Streamlit re-instantiates the page on every rerun, so the cookie
# manager has to be cached as a resource — building a new manager per
# rerun would lose its internal "I asked the browser, here's the
# answer" state and the get() call would return None forever.
_CACHE_KEY = "_ikigai_cookie_manager"


def _get_manager():
    """Return the singleton CookieManager for this Streamlit session.

    Returns None if the dep isn't installed or we're not inside a
    Streamlit runtime (so the helper degrades to a no-op cleanly).
    """
    if stx is None:
        return None
    if _CACHE_KEY not in st.session_state:
        try:
            st.session_state[_CACHE_KEY] = stx.CookieManager(key="ikigai_cookie_mgr")
        except Exception:
            # If CookieManager construction fails (e.g. Streamlit
            # context missing), don't blow up the app — just degrade
            # to no-cookie mode.
            return None
    return st.session_state[_CACHE_KEY]


def get_persisted_token() -> Optional[str]:
    """Return the stored bearer token, or None if no cookie / dep missing.

    Note: ``CookieManager.get`` may return None on the very first
    rerun even when the cookie is present — the value arrives on the
    next rerun. Callers should treat None as "no token yet" and let
    the UI show the login form; the next rerun will pick the cookie up.
    """
    mgr = _get_manager()
    if mgr is None:
        return None
    try:
        return mgr.get(cookie=_COOKIE_NAME)
    except Exception:
        return None


def persist_token(token: str) -> None:
    """Store *token* in the auth cookie for ``_COOKIE_TTL_HOURS`` hours."""
    mgr = _get_manager()
    if mgr is None:
        return
    expires = dt.datetime.utcnow() + dt.timedelta(hours=_COOKIE_TTL_HOURS)
    try:
        mgr.set(_COOKIE_NAME, token, expires_at=expires)
    except Exception:
        # Cookie writes can fail under unusual transports (custom
        # reverse proxies stripping Set-Cookie etc.). Log only, never
        # break the login flow.
        pass


def clear_persisted_token() -> None:
    """Delete the auth cookie so the next page load shows the login form."""
    mgr = _get_manager()
    if mgr is None:
        return
    try:
        mgr.delete(_COOKIE_NAME)
    except KeyError:
        # Cookie didn't exist — that's fine, the desired state is "no
        # cookie" and we're already there.
        pass
    except Exception:
        pass
