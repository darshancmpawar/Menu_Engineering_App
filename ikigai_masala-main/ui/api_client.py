"""
HTTP client for the Menu Planning Flask API.
"""

import requests
from typing import Dict, List, Optional, Any


class MenuApiClient:
    """Wrapper around the Flask API endpoints."""

    def __init__(self, base_url: str = "http://localhost:5000"):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()

    def health(self) -> Dict[str, Any]:
        resp = self.session.get(f"{self.base_url}/api/v1/health", timeout=5)
        resp.raise_for_status()
        return resp.json()

    def list_clients(self) -> List[str]:
        resp = self.session.get(f"{self.base_url}/api/v1/clients", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success"):
            raise RuntimeError(data.get("error", "Unknown error"))
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
            f"{self.base_url}/api/v1/plan", json=payload, timeout=time_limit_seconds + 30
        )
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        if not resp.ok or not data.get("success"):
            raise RuntimeError(data.get("error", f"Server error {resp.status_code}"))
        return data

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
            f"{self.base_url}/api/v1/regenerate", json=payload, timeout=time_limit_seconds + 30
        )
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        if not resp.ok or not data.get("success"):
            raise RuntimeError(data.get("error", f"Server error {resp.status_code}"))
        return data

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
            f"{self.base_url}/api/v1/save", json=payload, timeout=30
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success"):
            raise RuntimeError(data.get("error", "Save failed"))
        return data

    # ----- Customisation editor endpoints -----

    def get_editor_metadata(self) -> Dict[str, Any]:
        resp = self.session.get(f"{self.base_url}/api/v1/editor-metadata", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success"):
            raise RuntimeError(data.get("error", "Failed to load metadata"))
        return data

    def get_client_config(self, client_name: str) -> Dict[str, Any]:
        resp = self.session.get(
            f"{self.base_url}/api/v1/client-config/{client_name}", timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success"):
            raise RuntimeError(data.get("error", "Failed to load config"))
        return data

    def update_client_config(self, client_name: str, config: Dict[str, Any]) -> Dict[str, Any]:
        resp = self.session.put(
            f"{self.base_url}/api/v1/client-config/{client_name}",
            json=config, timeout=10
        )
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        if not resp.ok or not data.get("success"):
            raise RuntimeError(data.get("error", f"Save failed ({resp.status_code})"))
        return data

    def create_client(self, name: str, menu_category: str) -> Dict[str, Any]:
        resp = self.session.post(
            f"{self.base_url}/api/v1/client",
            json={"name": name, "menu_category": menu_category}, timeout=10
        )
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        if not resp.ok or not data.get("success"):
            raise RuntimeError(data.get("error", f"Create failed ({resp.status_code})"))
        return data

    def delete_client(self, client_name: str) -> Dict[str, Any]:
        resp = self.session.delete(
            f"{self.base_url}/api/v1/client/{client_name}", timeout=10
        )
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        if not resp.ok or not data.get("success"):
            raise RuntimeError(data.get("error", f"Delete failed ({resp.status_code})"))
        return data
