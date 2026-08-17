"""Tests for optimistic-concurrency on PUT /api/v1/client-config/<name>.

Two admins editing the same client at once used to last-write-wins
silently. GET now returns a ``version`` counter (also in an ``ETag``
response header); PUT must send that version back via either the body
or an ``If-Match`` header, and mismatched versions return 409 with the
current version in the body so the client can refresh + retry.
"""

import pytest

flask = pytest.importorskip("flask", reason="Flask not installed")
from api.app import app


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def auth_headers():
    """No-op header map; the API is now public (auth removed)."""
    return {}


class TestGetSurfacesVersion:
    def test_body_includes_version(self, client, auth_headers, fake_supabase):
        resp = client.get('/api/v1/client-config/Rippling', headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['version'] == 1

    def test_response_carries_etag(self, client, auth_headers, fake_supabase):
        resp = client.get('/api/v1/client-config/Rippling', headers=auth_headers)
        assert resp.headers['ETag'] == '"1"'


class TestPutRequiresVersion:
    def test_missing_version_returns_400(self, client, auth_headers, fake_supabase):
        resp = client.put(
            '/api/v1/client-config/Rippling',
            json={'theme_map': {'monday': 'mix'}},
            headers=auth_headers,
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert data['success'] is False
        assert 'version is required' in data['error']

    def test_non_integer_version_returns_400(self, client, auth_headers, fake_supabase):
        resp = client.put(
            '/api/v1/client-config/Rippling',
            json={'version': 'one', 'theme_map': {}},
            headers=auth_headers,
        )
        assert resp.status_code == 400


class TestPutAcceptsGoodVersion:
    def test_matching_version_succeeds_and_bumps(
        self, client, auth_headers, fake_supabase,
    ):
        resp = client.put(
            '/api/v1/client-config/Rippling',
            json={'version': 1, 'theme_map': {'monday': 'mix'}},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['version'] == 2
        assert resp.headers['ETag'] == '"2"'

        # A follow-up GET sees the new version.
        resp = client.get('/api/v1/client-config/Rippling', headers=auth_headers)
        assert resp.get_json()['version'] == 2

    def test_if_match_header_also_accepted(
        self, client, auth_headers, fake_supabase,
    ):
        headers = {**auth_headers, 'If-Match': '"1"'}
        resp = client.put(
            '/api/v1/client-config/Rippling',
            json={'theme_map': {'monday': 'mix'}},  # no body version
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.get_json()['version'] == 2


class TestPutRejectsStaleVersion:
    def test_stale_body_version_returns_409_with_current(
        self, client, auth_headers, fake_supabase,
    ):
        # Writer A bumps to 2 first.
        client.put(
            '/api/v1/client-config/Rippling',
            json={'version': 1, 'theme_map': {'monday': 'mix'}},
            headers=auth_headers,
        )
        # Writer B is still holding version=1 from their earlier GET.
        resp = client.put(
            '/api/v1/client-config/Rippling',
            json={'version': 1, 'theme_map': {'tuesday': 'chinese'}},
            headers=auth_headers,
        )
        assert resp.status_code == 409
        data = resp.get_json()
        assert data['success'] is False
        assert 'modified by another request' in data['error']
        assert data['current_version'] == 2

    def test_stale_if_match_header_returns_409(
        self, client, auth_headers, fake_supabase,
    ):
        client.put(
            '/api/v1/client-config/Rippling',
            json={'version': 1, 'theme_map': {'monday': 'mix'}},
            headers=auth_headers,
        )
        headers = {**auth_headers, 'If-Match': '"1"'}
        resp = client.put(
            '/api/v1/client-config/Rippling',
            json={'theme_map': {'tuesday': 'chinese'}},
            headers=headers,
        )
        assert resp.status_code == 409

    def test_conflict_does_not_partially_apply_updates(
        self, client, auth_headers, fake_supabase,
    ):
        """Version-mismatch rejection must happen before any sub-update
        runs, so a losing writer can't leave the DB half-changed."""
        client.put(
            '/api/v1/client-config/Rippling',
            json={'version': 1, 'theme_map': {'monday': 'chinese'}},
            headers=auth_headers,
        )

        # Capture the stored config (clients.counters) after writer A won.
        def _counters():
            row = [r for r in fake_supabase.rows('clients') if r['name'] == 'Rippling'][0]
            import copy
            return copy.deepcopy(row.get('counters'))
        after_winner = _counters()

        # Writer B tries with a stale version + a very different theme_map.
        resp = client.put(
            '/api/v1/client-config/Rippling',
            json={
                'version': 1,
                'theme_map': {'tuesday': 'biryani', 'wednesday': 'south'},
            },
            headers=auth_headers,
        )
        assert resp.status_code == 409

        after_loser = _counters()
        assert after_loser == after_winner, (
            "a rejected PUT must not modify clients.counters"
        )


class TestAtomicConfigUpdate:
    """PUT /client-config must validate everything before it writes anything.

    The handler used to bump `version` first and then run one setter per field,
    validating as it went. A malformed `source_pools` — the last field checked —
    returned 400 *after* city / serve_weekends / working_days /
    item_cooldown_days had been committed and the version incremented, so a
    single bad request left a half-updated row whose bumped version made the
    caller's retry 409.
    """

    CLIENT = 'Rippling'

    def _row(self, fake, name=None):
        return [
            r for r in fake._tables['clients'] if r['name'] == (name or self.CLIENT)
        ][0]

    def _put(self, client, body):
        return client.put(f'/api/v1/client-config/{self.CLIENT}', json=body)

    def test_invalid_source_pools_writes_nothing(self, fake_supabase):
        import api.app as api_app
        api_app.app.config['TESTING'] = True
        c = api_app.app.test_client()
        before = dict(self._row(fake_supabase))

        resp = self._put(c, {
            'version': before['version'], 'city': 'Pune',
            'serve_weekends': True, 'item_cooldown_days': 15,
            'source_pools': ['definitely_not_a_pool'],
        })
        assert resp.status_code == 400
        after = self._row(fake_supabase)
        assert after['version'] == before['version'], "version was bumped"
        assert after.get('city') == before.get('city')
        assert after.get('serve_weekends') == before.get('serve_weekends')
        assert after.get('item_cooldown_days') == before.get('item_cooldown_days')

    def test_invalid_working_days_writes_nothing(self, fake_supabase):
        import api.app as api_app
        api_app.app.config['TESTING'] = True
        c = api_app.app.test_client()
        before = dict(self._row(fake_supabase))

        resp = self._put(c, {
            'version': before['version'], 'city': 'Chennai',
            'working_days': ['funday'],
        })
        assert resp.status_code == 400
        after = self._row(fake_supabase)
        assert after['version'] == before['version']
        assert after.get('city') == before.get('city')

    def test_valid_update_applies_and_bumps_once(self, fake_supabase):
        import api.app as api_app
        api_app.app.config['TESTING'] = True
        c = api_app.app.test_client()
        before = dict(self._row(fake_supabase))

        resp = self._put(c, {
            'version': before['version'], 'city': 'Pune',
            'item_cooldown_days': 15, 'working_days': ['mon', 'Wednesday'],
        })
        assert resp.status_code == 200, resp.get_json()
        assert resp.get_json()['version'] == before['version'] + 1
        after = self._row(fake_supabase)
        assert after['city'] == 'Pune'
        assert after['item_cooldown_days'] == 15
        # abbreviations normalise to full lowercase names
        assert after['working_days'] == ['monday', 'wednesday']

    def test_stale_version_changes_nothing(self, fake_supabase):
        import api.app as api_app
        api_app.app.config['TESTING'] = True
        c = api_app.app.test_client()
        before = dict(self._row(fake_supabase))

        resp = self._put(c, {'version': before['version'] - 1, 'city': 'NCR'})
        assert resp.status_code == 409
        after = self._row(fake_supabase)
        assert after.get('city') == before.get('city')
        assert after['version'] == before['version']
