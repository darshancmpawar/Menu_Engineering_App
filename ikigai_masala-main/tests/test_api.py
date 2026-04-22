"""
Tests for the Flask API endpoints.

Uses Flask's test client (no running server needed).
"""

import datetime as dt
import json
import pytest

flask = pytest.importorskip("flask", reason="Flask not installed")
from api.app import app
import api.auth as api_auth
from api.auth import issue_token
from user_authentication.models import ROLE_SUPER_ADMIN


@pytest.fixture
def client():
    """Create a Flask test client."""
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def _auth_secret(monkeypatch):
    """Ensure API token signing has a deterministic test secret."""
    monkeypatch.setattr(api_auth, "API_SECRET_KEY", "test-secret-key")


@pytest.fixture
def auth_headers():
    """Bearer token for a super-admin test principal."""
    return {"Authorization": f"Bearer {issue_token('test@example.com', ROLE_SUPER_ADMIN)}"}


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        resp = client.get('/api/v1/health')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['status'] == 'healthy'


class TestRootEndpoint:
    def test_root_returns_api_info(self, client):
        resp = client.get('/')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['name'] == 'Ikigai Masala Menu Planning API'
        assert 'version' in data


class TestClientsEndpoint:
    def test_list_clients_returns_list(self, client, auth_headers, fake_supabase):
        resp = client.get('/api/v1/clients', headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert isinstance(data['clients'], list)
        assert 'Rippling' in data['clients']


class TestPlanEndpoint:
    def test_plan_requires_client_name(self, client, auth_headers):
        resp = client.post('/api/v1/plan', json={}, headers=auth_headers)
        assert resp.status_code == 400
        data = resp.get_json()
        assert data['success'] is False

    def test_plan_rejects_unknown_client(self, client, auth_headers, fake_supabase):
        resp = client.post('/api/v1/plan', json={
            'client_name': 'NonexistentClient999',
            'num_days': 1,
        }, headers=auth_headers)
        assert resp.status_code == 400
        data = resp.get_json()
        assert data['success'] is False
        assert 'Unknown client' in data['error']

    def test_plan_error_response_does_not_leak_exception_details(
        self, client, auth_headers, fake_supabase, monkeypatch,
    ):
        """Unexpected errors must surface a generic message, not the
        exception class name or raw message — those can reveal internal
        hostnames, schema names, etc."""
        import api.app as api_app

        class _SecretLeak(Exception):
            """Not in any specific handler — falls to the catch-all."""

        def _boom(*_a, **_k):
            raise _SecretLeak("supabase at 10.0.0.5 refused connection")

        monkeypatch.setattr(api_app, '_prepare_solver_inputs', _boom)
        resp = client.post('/api/v1/plan', json={
            'client_name': 'Rippling', 'num_days': 1,
        }, headers=auth_headers)
        assert resp.status_code == 500
        data = resp.get_json()
        assert data['success'] is False
        assert data['error'] == 'Internal server error'
        assert '10.0.0.5' not in data['error']
        assert '_SecretLeak' not in data['error']

    def test_plan_generates_for_valid_client(self, client, auth_headers, fake_supabase):
        resp = client.post('/api/v1/plan', json={
            'client_name': 'Rippling',
            'start_date': '2026-03-23',
            'num_days': 1,
            'time_limit_seconds': 30,
        }, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert 'solution' in data
        assert len(data['solution']) == 1


class TestRegenerateEndpoint:
    def test_regenerate_requires_client_name(self, client, auth_headers):
        resp = client.post('/api/v1/regenerate', json={}, headers=auth_headers)
        assert resp.status_code == 400
        data = resp.get_json()
        assert data['success'] is False

    def test_regenerate_requires_base_plan(self, client, auth_headers, fake_supabase):
        resp = client.post('/api/v1/regenerate', json={
            'client_name': 'Rippling',
        }, headers=auth_headers)
        assert resp.status_code == 400

    def test_regenerate_requires_replace_slots(self, client, auth_headers, fake_supabase):
        resp = client.post('/api/v1/regenerate', json={
            'client_name': 'Rippling',
            'base_plan': {'2026-03-23': {'bread': 'plain_chapatti(B)'}},
        }, headers=auth_headers)
        assert resp.status_code == 400


class TestSaveEndpoint:
    def test_save_requires_fields(self, client, auth_headers):
        resp = client.post('/api/v1/save', json={}, headers=auth_headers)
        assert resp.status_code == 400
        data = resp.get_json()
        assert data['success'] is False
        assert data['error'] == 'client_name is required'

    def test_save_rejects_unknown_client(self, client, auth_headers, fake_supabase):
        resp = client.post('/api/v1/save', json={
            'client_name': 'NonexistentClient999',
            'week_plan': {'2026-03-23': {'bread': 'plain_chapatti(B)'}},
            'week_start': '2026-03-23',
        }, headers=auth_headers)
        assert resp.status_code == 400
        data = resp.get_json()
        assert data['success'] is False
        assert 'Unknown client' in data['error']


class TestClientNamesRequestCache:
    """Within one request, client_names should be read from Supabase at most
    once; across separate requests, every request must hit Supabase again so
    live admin edits are visible without a restart."""

    def test_single_request_reads_client_names_once(
        self, client, auth_headers, fake_supabase, monkeypatch,
    ):
        import api.app as api_app

        calls = {"n": 0}
        real_loader = api_app._get_client_loader()

        class _CountingLoader:
            @property
            def client_names(self):
                calls["n"] += 1
                return real_loader.client_names

            def __getattr__(self, name):
                return getattr(real_loader, name)

        monkeypatch.setattr(api_app, "_get_client_loader", lambda: _CountingLoader())

        # /api/v1/clients both validates via the decorator (none here) and
        # reads client_names in the body. editor-metadata reads it too.
        # Use editor-metadata because it also pulls menu_categories — a
        # good smoke that multiple cached keys coexist.
        resp = client.get('/api/v1/editor-metadata', headers=auth_headers)
        assert resp.status_code == 200
        assert calls["n"] == 1, (
            f"expected 1 Supabase read of client_names per request, got {calls['n']}"
        )

    def test_separate_requests_each_refresh(
        self, client, auth_headers, fake_supabase, monkeypatch,
    ):
        import api.app as api_app

        calls = {"n": 0}
        real_loader = api_app._get_client_loader()

        class _CountingLoader:
            @property
            def client_names(self):
                calls["n"] += 1
                return real_loader.client_names

            def __getattr__(self, name):
                return getattr(real_loader, name)

        monkeypatch.setattr(api_app, "_get_client_loader", lambda: _CountingLoader())

        for _ in range(3):
            resp = client.get('/api/v1/clients', headers=auth_headers)
            assert resp.status_code == 200
        assert calls["n"] == 3, (
            "each request must re-read client_names so admin edits are "
            f"picked up live; got {calls['n']} reads across 3 requests"
        )

    def test_plan_validates_client_then_loads_config_on_same_read(
        self, client, auth_headers, fake_supabase, monkeypatch,
    ):
        """_require_known_client + the /plan body both want client_names.
        After this fix only one Supabase read should happen.
        """
        import api.app as api_app

        calls = {"n": 0}
        real_loader = api_app._get_client_loader()

        class _CountingLoader:
            @property
            def client_names(self):
                calls["n"] += 1
                return real_loader.client_names

            def __getattr__(self, name):
                return getattr(real_loader, name)

        monkeypatch.setattr(api_app, "_get_client_loader", lambda: _CountingLoader())

        resp = client.post('/api/v1/plan', json={
            'client_name': 'NonexistentClient999',
            'num_days': 1,
            'start_date': '2026-03-23',
        }, headers=auth_headers)
        # Unknown client → 400, but the request path still exercised the
        # validator's client_names read.
        assert resp.status_code == 400
        assert calls["n"] == 1
