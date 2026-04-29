"""Persistent auth-token storage via a browser cookie.

``st.session_state`` is per-Streamlit-session in-memory storage — it
dies on page hard-refresh, new tab, server restart, and Streamlit-Cloud
hibernation. To keep users signed in across those events the bearer
token has to live somewhere the *browser* keeps. We use a cookie.

Why ``streamlit-cookies-controller`` and not ``extra-streamlit-components``:

  Streamlit custom components are rendered inside a sandboxed iframe
  served from a different origin than the main app
  (e.g. ``qjmnz4vd2y0.streamlit.app`` vs ``yourapp.streamlit.app`` on
  Streamlit Cloud). ``extra-streamlit-components.CookieManager`` calls
  ``document.cookie = ...`` from inside that iframe, so the cookie
  lands on the iframe's origin — the browser never sends it back to
  the main app on refresh. This is the bug we hit in production.

  ``streamlit-cookies-controller.CookieController`` uses ``postMessage``
  to ask the *parent* window to set the cookie, putting it on the
  correct origin where the browser will replay it.

Cookie name: ``ikigai_auth``. Lifetime: 12 hours. The cookie value is
the same signed bearer token issued by ``POST /api/v1/auth/login``;
tampering invalidates the HMAC so the server rejects it on the next
request.

Async semantics: ``CookieController.getAll()`` returns ``{}`` on the
first render before the JS->Python handshake completes, then the
populated dict on the next rerun. ``app.py``'s warmup-flag pattern
handles that with one explicit ``st.rerun()``.
"""

from __future__ import annotations

import datetime as dt
from typing import Dict, Optional

import streamlit as st

# Lazily imported so test/script paths that don't run inside Streamlit
# don't pay the import cost or require the dep to be installed.
try:
    from streamlit_cookies_controller import CookieController
except ImportError:  # pragma: no cover — handled lazily by callers
    CookieController = None  # type: ignore[assignment,misc]


COOKIE_NAME = "ikigai_auth"
COOKIE_TTL_HOURS = 12
# Streamlit re-instantiates the page on every rerun, so the controller
# has to be cached as a singleton on session_state — building a new
# controller per rerun would lose its internal "I asked the browser,
# here's the answer" state and reads would never resolve.
_CACHE_KEY = "_ikigai_cookie_controller"


def _get_controller():
    """Return the per-session ``CookieController`` singleton.

    Returns ``None`` when the dep isn't installed or we're not inside
    a Streamlit runtime, so the helper degrades to a no-op cleanly
    (the caller's "no cookie" path takes over).
    """
    if CookieController is None:
        return None
    if _CACHE_KEY not in st.session_state:
        try:
            st.session_state[_CACHE_KEY] = CookieController(key="ikigai_cookie_ctl")
        except Exception:
            # Construction can fail outside a normal page-render
            # context (e.g. very early in app boot). Defer.
            return None
    return st.session_state[_CACHE_KEY]


def get_all_cookies() -> Optional[Dict[str, str]]:
    """Return every cookie the browser sent, as a dict.

    Returns:
        - ``None`` when the dep / controller isn't available — the
          frontend should fall back to "no persistence" mode silently.
        - ``{}`` either when the controller hasn't completed its
          first round-trip yet OR when there are genuinely no cookies.
          Callers disambiguate via a one-shot warmup flag in
          session_state (see ``app.py``).
        - ``{name: value, ...}`` once the controller is ready.
    """
    ctl = _get_controller()
    if ctl is None:
        return None
    try:
        # CookieController exposes getAll() (camelCase, not snake);
        # returns a dict of the cookies the parent window currently
        # holds for this origin.
        cookies = ctl.getAll() or {}
    except Exception:
        return None
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
    ctl = _get_controller()
    if ctl is None:
        return
    expires = dt.datetime.utcnow() + dt.timedelta(hours=COOKIE_TTL_HOURS)
    try:
        # same_site='lax' is the modern web default — 'strict' would
        # break cross-tab navigation. secure is left to the browser
        # (None) so localhost dev (http) still works alongside prod
        # (https on Streamlit Cloud).
        ctl.set(
            COOKIE_NAME, token,
            expires=expires,
            same_site="lax",
        )
    except Exception:
        # Cookie writes can fail under unusual transports / proxy
        # configurations. Log only, never break the login flow.
        pass


def clear_persisted_token() -> None:
    """Delete the auth cookie so the next page load shows the login form."""
    ctl = _get_controller()
    if ctl is None:
        return
    try:
        ctl.remove(COOKIE_NAME, same_site="lax")
    except KeyError:
        # Cookie didn't exist — that's fine, the desired state is "no
        # cookie" and we're already there.
        pass
    except Exception:
        pass
