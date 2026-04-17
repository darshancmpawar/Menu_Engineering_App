"""
HTTP client for the Menu Planning Flask API.
"""

import requests
from typing import Dict, List, Optional, Any


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
        resp = self.session.get(
            f"{self.base_url}/api/v1/clients", timeout=10, headers=self._auth_headers(),
        )
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
        resp = self.session.post(
            f"{self.base_url}/api/v1/plan", json=payload,
            timeout=time_limit_seconds + 30, headers=self._auth_headers(),
        )
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
        resp = self.session.post(
            f"{self.base_url}/api/v1/regenerate", json=payload,
            timeout=time_limit_seconds + 30, headers=self._auth_headers(),
        )
        return _parse_response(resp, "Regenerate failed")

    def save(
        self,
        client_name: str,
        week_plan: Dict[str, Dict[str, str]],
        week_start: str,
    ) -> Dict[str, Any]:
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
        resp = self.session.get(
            f"{self.base_url}/api/v1/editor-metadata", timeout=10,
            headers=self._auth_headers(),
        )
        return _parse_response(resp, "Failed to load metadata")

    def get_client_config(self, client_name: str) -> Dict[str, Any]:
        resp = self.session.get(
            f"{self.base_url}/api/v1/client-config/{client_name}", timeout=10,
            headers=self._auth_headers(),
        )
        return _parse_response(resp, "Failed to load config")

    def update_client_config(self, client_name: str, config: Dict[str, Any]) -> Dict[str, Any]:
        resp = self.session.put(
            f"{self.base_url}/api/v1/client-config/{client_name}",
            json=config, timeout=10, headers=self._auth_headers(),
        )
        return _parse_response(resp, "Save failed")

    def create_client(self, name: str, active_slots: list) -> Dict[str, Any]:
        resp = self.session.post(
            f"{self.base_url}/api/v1/client",
            json={"name": name, "active_slots": active_slots},
            timeout=10, headers=self._auth_headers(),
        )
        return _parse_response(resp, "Create failed")

    def delete_client(self, client_name: str) -> Dict[str, Any]:
        resp = self.session.delete(
            f"{self.base_url}/api/v1/client/{client_name}", timeout=10,
            headers=self._auth_headers(),
        )
        return _parse_response(resp, "Delete failed")
