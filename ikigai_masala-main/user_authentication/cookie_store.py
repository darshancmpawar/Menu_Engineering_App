"""Persistent auth-token storage via a browser cookie.

``st.session_state`` is per-Streamlit-session in-memory storage — it
dies on page hard-refresh, new tab, server restart, and Streamlit-Cloud
hibernation. To keep users signed in across those events the bearer
token has to live somewhere the *browser* keeps. We use a cookie
(via extra-streamlit-components).

Cookie name: ``ikigai_auth``. Lifetime: 12 hours (matches the policy
agreed with the operator). The cookie value is the same signed bearer
token issued by ``POST /api/v1/auth/login``; tampering invalidates the
HMAC so the server rejects it on the next request.

Important: ``CookieManager`` reads are **asynchronous**. The first
call after the component mounts always returns an empty / None value
because the cookie payload travels from the browser back to Python on
the next render cycle. Callers that want a synchronous "is the user
authenticated by cookie?" answer must:

  1. call :func:`get_all_cookies` once,
  2. if it returns ``{}`` (or ``None``), ``st.rerun()`` once with a
     warmup flag in session_state to avoid an infinite loop,
  3. on the second pass, ``get_all_cookies`` will return the populated
     dict (or a confirmed-empty dict if there's no cookie).

``app.py::_try_restore_session_from_cookie`` does exactly that.
"""

from __future__ import annotations

import datetime as dt
from typing import Dict, Optional

import streamlit as st

# Lazily imported so test/script paths that don't run inside Streamlit
# don't pay the import cost or require the dep to be installed.
try:
    import extra_streamlit_components as stx
except ImportError:  # pragma: no cover — handled lazily by callers
    stx = None  # type: ignore[assignment]


COOKIE_NAME = "ikigai_auth"
COOKIE_TTL_HOURS = 12
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


def get_all_cookies() -> Optional[Dict[str, str]]:
    """Return every cookie the browser sent, as a dict.

    Returns:
        - ``None`` when the dep / manager isn't available — the
          frontend should fall back to "no persistence" mode silently.
        - ``{}`` either when the cookie manager hasn't completed its
          first round-trip yet OR when there are genuinely no cookies.
          Callers disambiguate via a one-shot warmup flag in
          session_state.
        - ``{name: value, ...}`` once the manager is ready.
    """
    mgr = _get_manager()
    if mgr is None:
        return None
    try:
        # ``get_all()`` is the API that triggers the component-to-Python
        # rerun on first call. ``get(cookie=name)`` does NOT trigger
        # the rerun, which was the original bug: we'd read None on
        # first call and never get a second chance.
        cookies = mgr.get_all() or {}
    except Exception:
        return None
    # Cast values to str defensively — extra-streamlit-components
    # sometimes returns numbers / bools depending on the cookie
    # source.
    return {k: str(v) for k, v in cookies.items()}


def get_persisted_token() -> Optional[str]:
    """Return the auth-token cookie value, or None.

    Convenience wrapper around :func:`get_all_cookies` for callers that
    don't need to inspect the warmup state — typically anything that
    runs *after* the auth gate has already established the session.
    """
    cookies = get_all_cookies()
    if not cookies:
        return None
    return cookies.get(COOKIE_NAME)


def persist_token(token: str) -> None:
    """Store *token* in the auth cookie for ``COOKIE_TTL_HOURS`` hours."""
    mgr = _get_manager()
    if mgr is None:
        return
    expires = dt.datetime.utcnow() + dt.timedelta(hours=COOKIE_TTL_HOURS)
    try:
        mgr.set(COOKIE_NAME, token, expires_at=expires)
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
        mgr.delete(COOKIE_NAME)
    except KeyError:
        # Cookie didn't exist — that's fine, the desired state is "no
        # cookie" and we're already there.
        pass
    except Exception:
        pass
