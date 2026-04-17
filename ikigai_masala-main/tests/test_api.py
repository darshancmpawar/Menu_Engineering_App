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
    def test_list_clients_returns_list(self, client, auth_headers):
        resp = client.get('/api/v1/clients', headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert isinstance(data['clients'], list)
        assert len(data['clients']) > 0


class TestPlanEndpoint:
    def test_plan_requires_client_name(self, client, auth_headers):
        resp = client.post('/api/v1/plan', json={}, headers=auth_headers)
        assert resp.status_code == 400
        data = resp.get_json()
        assert data['success'] is False

    def test_plan_rejects_unknown_client(self, client, auth_headers):
        resp = client.post('/api/v1/plan', json={
            'client_name': 'NonexistentClient999',
            'num_days': 1,
        }, headers=auth_headers)
        assert resp.status_code in (400, 500)
        data = resp.get_json()
        assert data['success'] is False

    def test_plan_generates_for_valid_client(self, client, auth_headers):
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

    def test_regenerate_requires_base_plan(self, client, auth_headers):
        resp = client.post('/api/v1/regenerate', json={
            'client_name': 'Rippling',
        }, headers=auth_headers)
        assert resp.status_code == 400

    def test_regenerate_requires_replace_slots(self, client, auth_headers):
        resp = client.post('/api/v1/regenerate', json={
            'client_name': 'Rippling',
            'base_plan': {'2026-03-23': {'bread': 'plain_chapatti(B)'}},
        }, headers=auth_headers)
        assert resp.status_code == 400


class TestSaveEndpoint:
    def test_save_requires_fields(self, client, auth_headers):
        resp = client.post('/api/v1/save', json={}, headers=auth_headers)
        assert resp.status_code in (400, 500)
        data = resp.get_json()
        assert data['success'] is False
