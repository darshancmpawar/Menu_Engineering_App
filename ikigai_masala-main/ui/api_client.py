"""
HTTP client for the Menu Planning Flask API.
"""

import random
import time
from typing import Any, Callable, Dict, List, Optional

import requests


# HTTP statuses where a one-shot retry is safe and likely to succeed:
#   503: solver_gate queue full — the request never ran server-side.
#   502/504: proxy hiccup — rare, but a single retry is cheap.
# 5xx beyond these (500, 501) usually mean a genuine server-side error
# that will repeat; don't retry those.
_RETRY_STATUSES = frozenset({502, 503, 504})
_RETRY_BACKOFF_MIN_SEC = 0.2
_RETRY_BACKOFF_MAX_SEC = 0.7


def _parse_response(resp: requests.Response, default_error: str) -> Dict[str, Any]:
    """Decode a JSON API response and raise on any non-success.

    Handles the API's common envelope: ``{"success": bool, ...}``. If the
    server returned HTML or a non-JSON body (for example a 502 from an
    upstream proxy), ``data`` becomes ``{}`` and the fallback message is
    built from the default prefix and status code.
    """
    ct = resp.headers.get("content-type", "")
    data: Dict[str, Any] = resp.json() if ct.startswith("application/json") else {}
    if not resp.ok or not data.get("success"):
        raise RuntimeError(data.get("error", f"{default_error} ({resp.status_code})"))
    return data


def _with_one_retry(
    do_request: Callable[[], requests.Response],
    *,
    retryable: bool,
    sleep: Callable[[float], None] = time.sleep,
    rng: Optional[random.Random] = None,
) -> requests.Response:
    """Run ``do_request``; if *retryable* and the response is a transient
    5xx, sleep with jitter and try once more.

    Kept as a tiny helper rather than baked into each method so the retry
    policy is visible in one place and testable without patching every
    call site. Injection seams for ``sleep`` + ``rng`` keep the tests
    deterministic without touching ``time`` globals.
    """
    resp = do_request()
    if not retryable or resp.status_code not in _RETRY_STATUSES:
        return resp
    backoff = (rng or random).uniform(_RETRY_BACKOFF_MIN_SEC, _RETRY_BACKOFF_MAX_SEC)
    sleep(backoff)
    return do_request()


class MenuApiClient:
    """Wrapper around the Flask API endpoints."""

    def __init__(self, base_url: str = "http://localhost:5000", token: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.token = token

    def set_token(self, token: Optional[str]) -> None:
        self.token = token

    def _auth_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def login(self, email: str, password: str) -> Dict[str, Any]:
        """Exchange credentials for a bearer token; stores the token on success."""
        resp = self.session.post(
            f"{self.base_url}/api/v1/auth/login",
            json={"email": email, "password": password},
            timeout=15,
        )
        data = _parse_response(resp, "Login failed")
        self.token = data["token"]
        return data

    def health(self) -> Dict[str, Any]:
        resp = self.session.get(f"{self.base_url}/api/v1/health", timeout=5)
        resp.raise_for_status()
        return resp.json()

    def list_clients(self) -> List[str]:
        def _do():
            return self.session.get(
                f"{self.base_url}/api/v1/clients", timeout=10,
                headers=self._auth_headers(),
            )
        resp = _with_one_retry(_do, retryable=True)
        data = _parse_response(resp, "Failed to list clients")
        return data["clients"]

    def plan(
        self,
        client_name: str,
        start_date: str,
        num_days: int = 5,
        time_limit_seconds: int = 240,
    ) -> Dict[str, Any]:
        payload = {
            "client_name": client_name,
            "start_date": start_date,
            "num_days": num_days,
            "time_limit_seconds": time_limit_seconds,
        }

        def _do():
            return self.session.post(
                f"{self.base_url}/api/v1/plan", json=payload,
                timeout=time_limit_seconds + 30, headers=self._auth_headers(),
            )
        # Retry is safe: /plan has no side effects (nothing is written
        # to history until /save), so the worst case is a second solve.
        resp = _with_one_retry(_do, retryable=True)
        return _parse_response(resp, "Plan failed")

    def regenerate(
        self,
        client_name: str,
        base_plan: Dict[str, Dict[str, str]],
        replace_slots: Dict[str, List[str]],
        start_date: Optional[str] = None,
        num_days: int = 5,
        time_limit_seconds: int = 240,
    ) -> Dict[str, Any]:
        payload = {
            "client_name": client_name,
            "base_plan": base_plan,
            "replace_slots": replace_slots,
            "num_days": num_days,
            "time_limit_seconds": time_limit_seconds,
        }
        if start_date:
            payload["start_date"] = start_date

        def _do():
            return self.session.post(
                f"{self.base_url}/api/v1/regenerate", json=payload,
                timeout=time_limit_seconds + 30, headers=self._auth_headers(),
            )
        resp = _with_one_retry(_do, retryable=True)
        return _parse_response(resp, "Regenerate failed")

    def save(
        self,
        client_name: str,
        week_plan: Dict[str, Dict[str, str]],
        week_start: str,
    ) -> Dict[str, Any]:
        # /save writes to menu_history — retrying could insert duplicate
        # rows if the first attempt actually reached the DB before 502/504.
        # Keep this one single-shot.
        payload = {
            "client_name": client_name,
            "week_plan": week_plan,
            "week_start": week_start,
        }
        resp = self.session.post(
            f"{self.base_url}/api/v1/save", json=payload, timeout=30,
            headers=self._auth_headers(),
        )
        return _parse_response(resp, "Save failed")

    # ----- Customisation editor endpoints -----

    def get_editor_metadata(self) -> Dict[str, Any]:
        def _do():
            return self.session.get(
                f"{self.base_url}/api/v1/editor-metadata", timeout=10,
                headers=self._auth_headers(),
            )
        resp = _with_one_retry(_do, retryable=True)
        return _parse_response(resp, "Failed to load metadata")

    def get_client_config(self, client_name: str) -> Dict[str, Any]:
        def _do():
            return self.session.get(
                f"{self.base_url}/api/v1/client-config/{client_name}", timeout=10,
                headers=self._auth_headers(),
            )
        resp = _with_one_retry(_do, retryable=True)
        return _parse_response(resp, "Failed to load config")

    def update_client_config(self, client_name: str, config: Dict[str, Any]) -> Dict[str, Any]:
        # PUT is idempotent thanks to the optimistic version check — a
        # retry after 502/504 is safe: either the first call landed
        # (second gets 409), or it didn't (second applies cleanly).
        def _do():
            return self.session.put(
                f"{self.base_url}/api/v1/client-config/{client_name}",
                json=config, timeout=10, headers=self._auth_headers(),
            )
        resp = _with_one_retry(_do, retryable=True)
        return _parse_response(resp, "Save failed")

    def create_client(self, name: str, active_slots: list) -> Dict[str, Any]:
        # Creating the same name twice is caught server-side (409 / "already
        # exists"), so a retry after a proxy 502 is self-correcting.
        def _do():
            return self.session.post(
                f"{self.base_url}/api/v1/client",
                json={"name": name, "active_slots": active_slots},
                timeout=10, headers=self._auth_headers(),
            )
        resp = _with_one_retry(_do, retryable=True)
        return _parse_response(resp, "Create failed")

    def delete_client(self, client_name: str) -> Dict[str, Any]:
        # Idempotent: if the first call landed, the second gets 404.
        def _do():
            return self.session.delete(
                f"{self.base_url}/api/v1/client/{client_name}", timeout=10,
                headers=self._auth_headers(),
            )
        resp = _with_one_retry(_do, retryable=True)
        return _parse_response(resp, "Delete failed")
