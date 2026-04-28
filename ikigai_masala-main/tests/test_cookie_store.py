"""Tests for the persistent-login cookie store.

The hard part of the cookie-rehydrate flow lives in the Streamlit
script itself (app.py::_try_restore_session_from_cookie) and is
genuinely difficult to unit-test without a Streamlit runtime. These
tests cover the lower-level primitives in
``user_authentication.cookie_store``: the read paths, the no-dep
fallback, and the constants every caller depends on.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


# Streamlit imports cookie_store at module load. The session_state
# fixture mocks it so the module-level import succeeds without a
# Streamlit runtime.
@pytest.fixture(autouse=True)
def _streamlit_session_state(monkeypatch):
    """Replace st.session_state with a plain dict for the duration of
    each test, so the singleton-cache logic in cookie_store has
    somewhere to write without needing a Streamlit context."""
    import streamlit as st

    fake_state = {}
    monkeypatch.setattr(st, "session_state", fake_state)
    yield fake_state


def _stub_manager(cookies_returned):
    """Build a CookieManager-shaped stub whose get_all() returns the
    given value. Signals 'still warming up' with {} or None, signals
    'loaded' with a populated dict."""
    mgr = MagicMock(name="CookieManager")
    mgr.get_all.return_value = cookies_returned
    return mgr


def _install_stub_manager(monkeypatch, mgr):
    """Patch cookie_store._get_manager to return the given stub."""
    from user_authentication import cookie_store
    monkeypatch.setattr(cookie_store, "_get_manager", lambda: mgr)


class TestGetAllCookies:
    def test_returns_none_when_dep_missing(self, monkeypatch):
        from user_authentication import cookie_store
        monkeypatch.setattr(cookie_store, "_get_manager", lambda: None)
        assert cookie_store.get_all_cookies() is None

    def test_returns_empty_dict_when_manager_warming_up(self, monkeypatch):
        """First call returns {} — the component hasn't received the
        browser's cookies yet. Caller must rerun to disambiguate."""
        _install_stub_manager(monkeypatch, _stub_manager({}))
        from user_authentication import cookie_store
        assert cookie_store.get_all_cookies() == {}

    def test_returns_empty_dict_when_get_all_returns_none(self, monkeypatch):
        """Some versions of CookieManager return None instead of {}.
        Both must be normalised to {} so the warmup logic works."""
        _install_stub_manager(monkeypatch, _stub_manager(None))
        from user_authentication import cookie_store
        assert cookie_store.get_all_cookies() == {}

    def test_returns_loaded_cookies_dict(self, monkeypatch):
        _install_stub_manager(
            monkeypatch,
            _stub_manager({"ikigai_auth": "abc.def.ghi", "other": "x"}),
        )
        from user_authentication import cookie_store
        result = cookie_store.get_all_cookies()
        assert result == {"ikigai_auth": "abc.def.ghi", "other": "x"}

    def test_coerces_non_string_values_to_str(self, monkeypatch):
        """Defensive: extra-streamlit-components can sometimes return
        numbers / bools depending on the cookie source."""
        _install_stub_manager(
            monkeypatch, _stub_manager({"flag": True, "n": 42}),
        )
        from user_authentication import cookie_store
        result = cookie_store.get_all_cookies()
        assert result == {"flag": "True", "n": "42"}

    def test_returns_none_on_unexpected_exception(self, monkeypatch):
        """A misbehaving cookie manager (e.g. transport stripped the
        component channel) must NOT crash the auth gate."""
        mgr = MagicMock()
        mgr.get_all.side_effect = RuntimeError("ws closed")
        _install_stub_manager(monkeypatch, mgr)
        from user_authentication import cookie_store
        assert cookie_store.get_all_cookies() is None


class TestGetPersistedToken:
    """Convenience wrapper around get_all_cookies — used by callers
    that don't need to inspect the warmup state (i.e. anything that
    runs after the auth gate has already established the session)."""

    def test_returns_token_when_cookie_present(self, monkeypatch):
        from user_authentication import cookie_store
        _install_stub_manager(
            monkeypatch,
            _stub_manager({cookie_store.COOKIE_NAME: "the-token"}),
        )
        assert cookie_store.get_persisted_token() == "the-token"

    def test_returns_none_when_cookie_missing(self, monkeypatch):
        _install_stub_manager(
            monkeypatch, _stub_manager({"unrelated": "x"}),
        )
        from user_authentication import cookie_store
        assert cookie_store.get_persisted_token() is None

    def test_returns_none_when_warming_up(self, monkeypatch):
        """get_persisted_token can't tell warming-up apart from
        no-cookie; it returns None for both. The warmup
        disambiguation is the auth-gate's job, not this helper's."""
        _install_stub_manager(monkeypatch, _stub_manager({}))
        from user_authentication import cookie_store
        assert cookie_store.get_persisted_token() is None


class TestPersistTokenWriteSafety:
    """The write path is fire-and-forget (the component channel
    dispatches the cookie set asynchronously). We just need to confirm
    it doesn't blow up in the no-dep / exception cases."""

    def test_persist_no_op_when_dep_missing(self, monkeypatch):
        from user_authentication import cookie_store
        monkeypatch.setattr(cookie_store, "_get_manager", lambda: None)
        # Must not raise.
        cookie_store.persist_token("anything")

    def test_persist_swallows_exceptions(self, monkeypatch):
        mgr = MagicMock()
        mgr.set.side_effect = RuntimeError("set-cookie blocked")
        _install_stub_manager(monkeypatch, mgr)
        from user_authentication import cookie_store
        # A misbehaving cookie write must NOT block the login flow.
        cookie_store.persist_token("anything")

    def test_persist_calls_set_with_cookie_name_and_token(self, monkeypatch):
        mgr = MagicMock()
        _install_stub_manager(monkeypatch, mgr)
        from user_authentication import cookie_store
        cookie_store.persist_token("the-bearer")
        # First positional arg is the cookie name; second is the value.
        args, kwargs = mgr.set.call_args
        assert args[0] == cookie_store.COOKIE_NAME
        assert args[1] == "the-bearer"
        # expires_at is in the future and roughly TTL hours away.
        import datetime as dt
        assert "expires_at" in kwargs
        delta = kwargs["expires_at"] - dt.datetime.utcnow()
        # Allow some slack for clock drift / test runtime.
        assert dt.timedelta(hours=cookie_store.COOKIE_TTL_HOURS - 1) <= delta
        assert delta <= dt.timedelta(hours=cookie_store.COOKIE_TTL_HOURS + 1)


class TestClearPersistedToken:
    def test_clear_no_op_when_dep_missing(self, monkeypatch):
        from user_authentication import cookie_store
        monkeypatch.setattr(cookie_store, "_get_manager", lambda: None)
        cookie_store.clear_persisted_token()  # must not raise

    def test_clear_calls_delete_with_cookie_name(self, monkeypatch):
        mgr = MagicMock()
        _install_stub_manager(monkeypatch, mgr)
        from user_authentication import cookie_store
        cookie_store.clear_persisted_token()
        mgr.delete.assert_called_once_with(cookie_store.COOKIE_NAME)

    def test_clear_swallows_keyerror_when_cookie_already_absent(
        self, monkeypatch,
    ):
        mgr = MagicMock()
        mgr.delete.side_effect = KeyError(
            "cookie wasn't there to delete"
        )
        _install_stub_manager(monkeypatch, mgr)
        from user_authentication import cookie_store
        # The desired state is "no cookie" — already there is fine.
        cookie_store.clear_persisted_token()
