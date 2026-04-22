"""Tests for bearer-token auth on the Flask API.

These tests exercise the decorator and role gating directly by forging tokens
via ``api.auth.issue_token`` — they do not hit the /auth/login endpoint, which
would require Supabase.
"""

import pytest

pytest.importorskip("flask", reason="Flask not installed")

import api.auth as api_auth
from api.app import app
from api.auth import issue_token
from user_authentication.models import ROLE_ADMIN, ROLE_SUPER_ADMIN, ROLE_USER


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def _auth_secret(monkeypatch):
    """Ensure bearer token tests use an explicit signing secret."""
    monkeypatch.setattr(api_auth, "API_SECRET_KEY", "test-secret-key")


def _bearer(role: str) -> dict:
    return {"Authorization": f"Bearer {issue_token('t@e.com', role)}"}


class TestPublicRoutes:
    def test_health_is_public(self, client):
        assert client.get('/api/v1/health').status_code == 200

    def test_root_is_public(self, client):
        assert client.get('/').status_code == 200


class TestProtectedRoutesRejectAnon:
    @pytest.mark.parametrize("method, path", [
        ("get", "/api/v1/clients"),
        ("post", "/api/v1/plan"),
        ("post", "/api/v1/regenerate"),
        ("post", "/api/v1/save"),
        ("get", "/api/v1/editor-metadata"),
        ("get", "/api/v1/client-config/Rippling"),
        ("put", "/api/v1/client-config/Rippling"),
        ("post", "/api/v1/client"),
        ("delete", "/api/v1/client/Rippling"),
        ("post", "/api/v1/validate-pools"),
    ])
    def test_missing_token_returns_401(self, client, method, path):
        resp = getattr(client, method)(path, json={})
        assert resp.status_code == 401
        assert resp.get_json()["success"] is False


class TestTokenValidation:
    def test_malformed_token_rejected(self, client):
        resp = client.get(
            '/api/v1/clients',
            headers={"Authorization": "Bearer not-a-real-token"},
        )
        assert resp.status_code == 401

    def test_valid_token_passes_auth(self, client, fake_supabase):
        # fake_supabase swaps in the in-memory fake so the handler can
        # actually answer; the assertion is that a valid token is not
        # rejected by the auth decorator.
        resp = client.get('/api/v1/clients', headers=_bearer(ROLE_USER))
        assert resp.status_code not in (401, 403)


class TestRoleGating:
    def test_user_forbidden_from_admin_routes(self, client):
        resp = client.post(
            '/api/v1/client',
            json={'name': 'X', 'active_slots': []},
            headers=_bearer(ROLE_USER),
        )
        assert resp.status_code == 403

    def test_admin_passes_role_check(self, client):
        # Empty body → 400, but it got past the auth decorator, which is what we assert.
        resp = client.post(
            '/api/v1/client',
            json={},
            headers=_bearer(ROLE_ADMIN),
        )
        assert resp.status_code not in (401, 403)

    def test_super_admin_passes_role_check(self, client):
        resp = client.post(
            '/api/v1/client',
            json={},
            headers=_bearer(ROLE_SUPER_ADMIN),
        )
        assert resp.status_code not in (401, 403)


class TestLoginEndpointShape:
    def test_login_requires_credentials(self, client):
        resp = client.post('/api/v1/auth/login', json={})
        assert resp.status_code == 400
        assert resp.get_json()["success"] is False


class TestSecretKeySafety:
    def test_issue_token_fails_when_secret_unset(self, monkeypatch):
        monkeypatch.setattr(api_auth, "API_SECRET_KEY", "")
        with pytest.raises(RuntimeError, match="API_SECRET_KEY is required"):
            issue_token("x@test.com", ROLE_USER)
