"""
Tests for the Flask API endpoints.

Uses Flask's test client (no running server needed).
"""

import pytest

flask = pytest.importorskip("flask", reason="Flask not installed")
from api.app import app


@pytest.fixture
def client():
    """Create a Flask test client."""
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def auth_headers():
    """No-op header map. Authentication was removed from the API, so
    endpoints are public; this fixture stays as ``{}`` to keep the
    many call sites that pass ``headers=auth_headers`` unchanged."""
    return {}


class TestHealthEndpoint:
    def test_health_returns_healthy_when_supabase_reachable(
        self, client, fake_supabase,
    ):
        resp = client.get('/api/v1/health')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['status'] == 'healthy'
        assert data['supabase_reachable'] is True
        assert data['version']
        assert isinstance(data['uptime_seconds'], int)
        assert 'queue' in data
        # Schema field added in Tier 1 #4.
        assert data['schema']['status'] == 'ok'
        assert data['schema']['missing'] == []

    def test_health_returns_degraded_when_supabase_down(
        self, client, monkeypatch,
    ):
        """Kubernetes readiness / uptime-robot callers should see a 503
        when the backing store is unreachable so they stop routing traffic."""
        import api.app as api_app

        # _probe_supabase now returns (reachable, schema_info).
        monkeypatch.setattr(
            api_app, '_probe_supabase',
            lambda: (False, {"status": "unknown", "missing": []}),
        )

        resp = client.get('/api/v1/health')
        assert resp.status_code == 503
        data = resp.get_json()
        assert data['status'] == 'degraded'
        assert data['supabase_reachable'] is False

    def test_health_error_still_logs_access_line(
        self, client, caplog, monkeypatch,
    ):
        """Failing health checks should surface in the access log even
        though successful ones are intentionally quiet."""
        import api.app as api_app
        import logging
        caplog.set_level(logging.INFO, logger="api.app")

        monkeypatch.setattr(
            api_app, '_probe_supabase',
            lambda: (False, {"status": "unknown", "missing": []}),
        )

        client.get('/api/v1/health')
        http_lines = [r for r in caplog.records if r.getMessage() == 'http_request']
        assert any(r.path == '/api/v1/health' for r in http_lines), (
            "a 503 on /health must show up in the access log"
        )

    def test_health_reports_drift_but_stays_200_when_only_schema_is_off(
        self, client, monkeypatch,
    ):
        """Tier 1 #4 — if Supabase is reachable but a required column is
        missing (e.g. the Phase 2 #14 migration wasn't applied), /health
        must report ``schema.status == "drift_detected"`` so operators
        notice on the next ping. HTTP status stays 200 — the runtime
        fallback in client_config.py keeps the app serving, and a 503
        here would page on-call for a "please run a migration" task."""
        import api.app as api_app
        monkeypatch.setattr(
            api_app, '_probe_supabase',
            lambda: (True, {"status": "drift_detected",
                            "missing": ["clients.version"]}),
        )

        resp = client.get('/api/v1/health')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['status'] == 'healthy', (
            "drift is human-fix-required; not an alerting condition"
        )
        assert data['schema']['status'] == 'drift_detected'
        assert 'clients.version' in data['schema']['missing']

    def test_probe_supabase_detects_undefined_column(
        self, client, monkeypatch, caplog,
    ):
        """End-to-end: the ``select('name, version')`` probe query
        must classify a 42703 (column does not exist) error from
        Supabase as drift_detected and log the actionable ERROR — not
        as 'unreachable'."""
        import api.app as api_app
        import logging

        caplog.set_level(logging.ERROR, logger="api.app")

        # Reset the once-per-occurrence flag so this test always sees
        # the ERROR log regardless of what other tests did first.
        api_app._drift_logged = False

        class _Pg42703(Exception):
            code = "42703"

        class _Stub:
            def table(self, _name):
                class _T:
                    def select(self_inner, *_a, **_kw): return self_inner
                    def limit(self_inner, _n): return self_inner
                    def execute(self_inner):
                        raise _Pg42703('column "version" does not exist')
                return _T()

        monkeypatch.setattr(
            'src.db.get_supabase', lambda: _Stub(),
        )
        reachable, schema_info = api_app._probe_supabase()
        assert reachable is True
        assert schema_info["status"] == "drift_detected"
        assert "clients.version" in schema_info["missing"]
        # Loud error logged once per drift episode.
        assert any(
            "Schema drift" in rec.message and "scripts/setup_all.sql" in rec.message
            for rec in caplog.records
        )

    def test_probe_supabase_dedupes_drift_log(
        self, client, monkeypatch, caplog,
    ):
        """Successive /health hits during a sustained drift state must
        log the ERROR only once — otherwise an uptime monitor pinging
        every 30s floods the log."""
        import api.app as api_app
        import logging
        caplog.set_level(logging.ERROR, logger="api.app")
        api_app._drift_logged = False

        class _Pg42703(Exception):
            code = "42703"

        class _Stub:
            def table(self, _name):
                class _T:
                    def select(self_inner, *_a, **_kw): return self_inner
                    def limit(self_inner, _n): return self_inner
                    def execute(self_inner):
                        raise _Pg42703("column does not exist")
                return _T()

        monkeypatch.setattr('src.db.get_supabase', lambda: _Stub())

        for _ in range(5):
            api_app._probe_supabase()

        drift_logs = [
            rec for rec in caplog.records
            if "Schema drift" in rec.message
        ]
        assert len(drift_logs) == 1, (
            f"expected exactly 1 drift log; got {len(drift_logs)} — "
            "dedupe regressed"
        )

    def test_probe_supabase_logs_recovery(
        self, client, monkeypatch, caplog,
    ):
        """When drift is fixed (operator runs the migration), the next
        /health probe must log a clear "drift cleared" INFO so on-call
        knows the alert can be silenced."""
        import api.app as api_app
        import logging
        caplog.set_level(logging.INFO, logger="api.app")

        # Pre-condition: drift was previously detected and logged.
        api_app._drift_logged = True

        class _OkStub:
            def table(self, _name):
                class _T:
                    def select(self_inner, *_a, **_kw): return self_inner
                    def limit(self_inner, _n): return self_inner
                    def execute(self_inner):
                        class _R:
                            data = []
                        return _R()
                return _T()

        monkeypatch.setattr('src.db.get_supabase', lambda: _OkStub())

        reachable, schema_info = api_app._probe_supabase()
        assert reachable is True
        assert schema_info["status"] == "ok"
        assert api_app._drift_logged is False  # flag reset
        assert any(
            "Schema drift cleared" in rec.message for rec in caplog.records
        )


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

    def test_list_clients_includes_city_detail(
        self, client, auth_headers, fake_supabase,
    ):
        client.post('/api/v1/client', json={
            'name': 'PuneCo', 'active_slots': ['rice', 'dal'], 'city': 'Pune',
        }, headers=auth_headers)
        data = client.get('/api/v1/clients', headers=auth_headers).get_json()
        by_name = {c['name']: c['city'] for c in data['clients_detail']}
        assert by_name['PuneCo'] == 'Pune'
        assert by_name['Rippling'] is None


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
        # Surface the request_id so an admin can grep the access log
        # for the real exception. Body still doesn't leak the message
        # itself, just the correlation id.
        assert 'request_id' in data
        assert data['request_id']
        assert resp.headers.get('X-Request-ID') == data['request_id']

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
        # Pre-flight surface always rides along on the 200 path so the
        # UI can render info/warning entries even on a successful plan.
        assert 'rule_diagnostics' in data
        assert 'summary' in data
        assert data['summary']['would_succeed'] is True

    def test_plan_returns_ranked_alternates(self, client, auth_headers, fake_supabase):
        resp = client.post('/api/v1/plan', json={
            'client_name': 'Rippling',
            'start_date': '2026-03-23',
            'num_days': 1,
            'time_limit_seconds': 30,
            'alternates': 2,
        }, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'solution' in data                       # primary (best) menu
        assert 'alternates' in data
        assert isinstance(data['alternates'], list)
        assert 1 <= len(data['alternates']) <= 2        # ranked, distinct from primary
        for alt in data['alternates']:
            assert len(alt) == 1                        # one day, fully formatted

    def test_plan_no_alternates_key_when_not_requested(
        self, client, auth_headers, fake_supabase,
    ):
        resp = client.post('/api/v1/plan', json={
            'client_name': 'Rippling', 'start_date': '2026-03-23',
            'num_days': 1, 'time_limit_seconds': 30,
        }, headers=auth_headers)
        assert resp.status_code == 200
        assert 'alternates' not in resp.get_json()

    def test_plan_reports_single_counter_metadata(
        self, client, auth_headers, fake_supabase,
    ):
        resp = client.post('/api/v1/plan', json={
            'client_name': 'Rippling', 'start_date': '2026-03-23',
            'num_days': 1, 'time_limit_seconds': 30,
        }, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['counter_mode'] == 'single'
        assert data['counter_count'] == 1
        assert data['counter_index'] == 0
        assert data['counter_name']


_VIABLE = ['welcome_drink', 'starter', 'soup', 'salad', 'rice', 'dal',
           'veg_gravy', 'veg_dry', 'bread', 'curd_side', 'dessert']


class TestMultiCounterPlanning:
    """Per-counter generate/save for a multi-cuisine client."""

    def _make_multi(self, client, auth_headers):
        resp = client.post('/api/v1/client', json={
            'name': 'MultiCo', 'counter_mode': 'multi',
            'counters': [
                {'name': 'Main', 'categories': _VIABLE, 'slot_counts': {}, 'theme_map': {}},
                {'name': 'Live', 'categories': _VIABLE, 'slot_counts': {},
                 'theme_map': {'monday': 'chinese'}},
            ],
        }, headers=auth_headers)
        assert resp.status_code == 200, resp.get_json()

    def test_plan_each_counter_independently(self, client, auth_headers, fake_supabase):
        self._make_multi(client, auth_headers)
        p0 = client.post('/api/v1/plan', json={
            'client_name': 'MultiCo', 'start_date': '2026-03-23', 'num_days': 1,
            'time_limit_seconds': 30, 'counter_index': 0,
        }, headers=auth_headers).get_json()
        p1 = client.post('/api/v1/plan', json={
            'client_name': 'MultiCo', 'start_date': '2026-03-23', 'num_days': 1,
            'time_limit_seconds': 30, 'counter_index': 1,
        }, headers=auth_headers).get_json()
        assert p0['success'] and p1['success']
        assert p0['counter_mode'] == 'multi' and p0['counter_count'] == 2
        assert p0['counter_name'] == 'Main' and p1['counter_name'] == 'Live'
        assert 'solution' in p0 and 'solution' in p1

    def test_plan_rejects_out_of_range_counter(self, client, auth_headers, fake_supabase):
        self._make_multi(client, auth_headers)
        resp = client.post('/api/v1/plan', json={
            'client_name': 'MultiCo', 'start_date': '2026-03-23', 'num_days': 1,
            'counter_index': 9,
        }, headers=auth_headers)
        assert resp.status_code == 400
        assert 'out of range' in resp.get_json()['error']

    def test_save_multi_counters_nested(self, client, auth_headers, fake_supabase):
        self._make_multi(client, auth_headers)
        resp = client.post('/api/v1/save', json={
            'client_name': 'MultiCo', 'week_start': '2026-03-23',
            'counters': [
                {'name': 'Main', 'week_plan': {'2026-03-23': {'rice': 'jeera_rice(Y)', 'dal': 'tadka'}}},
                {'name': 'Live', 'week_plan': {'2026-03-23': {'starter': 'tikka(R)'}}},
            ],
        }, headers=auth_headers)
        assert resp.status_code == 200, resp.get_json()
        rows = fake_supabase.rows('menu_history')
        assert len(rows) == 1
        menu = rows[0]['menu']
        # Nested per counter, colour suffix stripped.
        assert set(menu.keys()) == {'Main', 'Live'}
        assert menu['Main'] == {'rice': 'jeera_rice', 'dal': 'tadka'}
        assert menu['Live'] == {'starter': 'tikka'}


class TestConstantSelection:
    """Constants (white_rice/papad/pickle/chutney) are per-client selectable
    now, not force-added to every client."""

    def test_only_selected_constants_appear(self, client, auth_headers, fake_supabase):
        client.post('/api/v1/client', json={
            'name': 'ConstCo', 'active_slots': _VIABLE + ['white_rice', 'papad'],
        }, headers=auth_headers)
        resp = client.post('/api/v1/plan', json={
            'client_name': 'ConstCo', 'start_date': '2026-03-23', 'num_days': 1,
            'time_limit_seconds': 30,
        }, headers=auth_headers)
        assert resp.status_code == 200
        day = next(iter(resp.get_json()['solution'].values()))
        slots = set(day.get('items', {}).keys())
        assert 'white_rice' in slots and 'papad' in slots
        assert 'pickle' not in slots and 'chutney' not in slots

    def test_no_constants_when_none_selected(self, client, auth_headers, fake_supabase):
        client.post('/api/v1/client', json={
            'name': 'NoConst', 'active_slots': _VIABLE,
        }, headers=auth_headers)
        resp = client.post('/api/v1/plan', json={
            'client_name': 'NoConst', 'start_date': '2026-03-23', 'num_days': 1,
            'time_limit_seconds': 30,
        }, headers=auth_headers)
        assert resp.status_code == 200
        day = next(iter(resp.get_json()['solution'].values()))
        slots = set(day.get('items', {}).keys())
        assert not ({'white_rice', 'papad', 'pickle', 'chutney'} & slots)


class TestDiagnoseEndpoint:
    """Coverage for the new /api/v1/diagnose pre-flight endpoint. The
    solver is never invoked here; we just verify the structured
    diagnostic envelope.
    """

    def test_requires_known_client(self, client, auth_headers, fake_supabase):
        resp = client.post('/api/v1/diagnose', json={
            'client_name': 'NotAClient',
            'start_date': '2026-03-23', 'num_days': 1,
        }, headers=auth_headers)
        assert resp.status_code == 400
        assert 'Unknown client' in resp.get_json()['error']

    def test_returns_structured_envelope(self, client, auth_headers, fake_supabase):
        resp = client.post('/api/v1/diagnose', json={
            'client_name': 'Rippling',
            'start_date': '2026-03-23', 'num_days': 1,
        }, headers=auth_headers)
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['success'] is True
        assert 'rule_diagnostics' in body
        assert 'summary' in body
        # Summary must carry the four canonical keys so the UI's badge
        # rendering doesn't have to .get() with defaults.
        for key in ('errors', 'warnings', 'infos', 'would_succeed'):
            assert key in body['summary']

    def test_diagnose_matches_plan_preflight_for_same_body(
        self, client, auth_headers, fake_supabase,
    ):
        """Drift guard: /diagnose and /plan's pre-flight pass share the
        same _run_preflight call, so identical bodies must yield
        identical diagnostics. A divergence here would mean a user
        could pass /diagnose then have /plan still 422 — which is the
        exact UX bug we're avoiding.
        """
        body = {
            'client_name': 'Rippling',
            'start_date': '2026-03-23', 'num_days': 1,
        }
        diag_resp = client.post('/api/v1/diagnose', json=body,
                                headers=auth_headers)
        # /plan also runs the same pre-flight and emits identical
        # diagnostics — needs time_limit_seconds for the solver, but
        # the solver shouldn't run if pre-flight errors. In the fake
        # supabase fixture no history is seeded, so no errors expected.
        plan_resp = client.post('/api/v1/plan', json={
            **body, 'time_limit_seconds': 30,
        }, headers=auth_headers)
        assert diag_resp.status_code == 200
        # /plan either runs to 200 (no errors) or returns 422 with
        # rule_diagnostics. Either way the diagnostic *list* must match.
        diag_list = diag_resp.get_json()['rule_diagnostics']
        plan_list = plan_resp.get_json().get('rule_diagnostics', [])
        # Compare as tuple of (rule, severity, message) — affected
        # carries pool counts that may shift if anything resamples.
        def _key(d):
            return (d['rule'], d['severity'], d['message'])
        assert sorted(_key(d) for d in diag_list) == sorted(
            _key(d) for d in plan_list
        )


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

    def test_save_then_save_again_overwrites_history(
        self, client, auth_headers, fake_supabase,
    ):
        """Re-saving the same week with a different plan replaces the
        previously stored rows. Without this, the cooldown rules would
        see two conflicting items for the same (date, slot) and
        ``/saved-plan`` couldn't reliably tell which one to return.
        """
        first = client.post('/api/v1/save', json={
            'client_name': 'Rippling',
            'week_plan': {'2026-03-23': {'rice': 'jeera_rice(Y)'}},
            'week_start': '2026-03-23',
        }, headers=auth_headers)
        assert first.status_code == 200
        rows = fake_supabase.rows('menu_history')
        # One JSONB day row; colour suffix stripped for storage.
        assert [r['menu'] for r in rows] == [{'rice': 'jeera_rice'}]

        second = client.post('/api/v1/save', json={
            'client_name': 'Rippling',
            'week_plan': {'2026-03-23': {'rice': 'lemon_rice(Y)'}},
            'week_start': '2026-03-23',
        }, headers=auth_headers)
        assert second.status_code == 200
        rows = fake_supabase.rows('menu_history')
        assert [r['menu'] for r in rows] == [{'rice': 'lemon_rice'}]
        # week_signatures also overwrites — exactly one row per
        # (client, week_start) post-save.
        assert len(fake_supabase.rows('week_signatures')) == 1


class TestSavedPlanEndpoint:
    """Coverage for the GET /api/v1/saved-plan readback that powers
    'Generate replays the saved plan if one exists' in the UI.
    """

    def test_rejects_unknown_client(self, client, auth_headers, fake_supabase):
        resp = client.get(
            '/api/v1/saved-plan?client_name=NotARealClient',
            headers=auth_headers,
        )
        assert resp.status_code == 400
        body = resp.get_json()
        assert body['success'] is False
        assert 'Unknown client' in body['error']

    def test_returns_exists_false_when_no_history(
        self, client, auth_headers, fake_supabase,
    ):
        resp = client.get(
            '/api/v1/saved-plan?client_name=Rippling'
            '&start_date=2026-03-23&num_days=2',
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['success'] is True
        assert body['exists'] is False
        assert body['covered_dates'] == []
        assert body['source'] == 'history'

    def test_save_then_load_round_trip(
        self, client, auth_headers, fake_supabase,
    ):
        """The big one: save a plan, then re-request via /saved-plan
        and confirm the response matches what the UI rendered. Covers
        the overwrite-on-save + load-from-history happy path the
        feature is built around.
        """
        # Save a 1-day plan (a Monday).
        save = client.post('/api/v1/save', json={
            'client_name': 'Rippling',
            'week_plan': {'2026-03-23': {'rice': 'jeera_rice(Y)',
                                          'bread': 'naan(B)'}},
            'week_start': '2026-03-23',
        }, headers=auth_headers)
        assert save.status_code == 200

        load = client.get(
            '/api/v1/saved-plan?client_name=Rippling'
            '&start_date=2026-03-23&num_days=1',
            headers=auth_headers,
        )
        assert load.status_code == 200
        body = load.get_json()
        assert body['exists'] is True
        assert body['covered_dates'] == ['2026-03-23']
        # solution shape matches /plan: {date: {theme, day_type, items}}.
        solution = body['solution']
        assert '2026-03-23' in solution
        day = solution['2026-03-23']
        assert 'items' in day
        assert set(day['items'].keys()) >= {'rice', 'bread'}
        # item_base is what was persisted; item still carries a color
        # suffix when the ontology has one (color is re-attached
        # server-side from the Excel df).
        rice = day['items']['rice']
        assert rice['item_base'] == 'jeera_rice'

    def test_partial_coverage_marks_exists_false(
        self, client, auth_headers, fake_supabase,
    ):
        """If only one of the two requested weekdays has saved rows the
        endpoint reports exists=False — the UI falls back to /plan
        instead of showing a half-empty table.
        """
        # Save only one date (Mon 23rd).
        client.post('/api/v1/save', json={
            'client_name': 'Rippling',
            'week_plan': {'2026-03-23': {'rice': 'jeera_rice(Y)'}},
            'week_start': '2026-03-23',
        }, headers=auth_headers)

        # Ask for two weekdays — Mon + Tue.
        resp = client.get(
            '/api/v1/saved-plan?client_name=Rippling'
            '&start_date=2026-03-23&num_days=2',
            headers=auth_headers,
        )
        body = resp.get_json()
        assert body['exists'] is False
        assert body['covered_dates'] == ['2026-03-23']


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
            # /api/v1/clients reads the name+city detail; count that.
            def list_clients_with_city(self):
                calls["n"] += 1
                return real_loader.list_clients_with_city()

            def __getattr__(self, name):
                return getattr(real_loader, name)

        monkeypatch.setattr(api_app, "_get_client_loader", lambda: _CountingLoader())

        for _ in range(3):
            resp = client.get('/api/v1/clients', headers=auth_headers)
            assert resp.status_code == 200
        assert calls["n"] == 3, (
            "each request must re-read the client list so admin edits are "
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


class TestEditorMetadataCounters:
    def test_metadata_exposes_max_counters(
        self, client, auth_headers, fake_supabase,
    ):
        from src.client.client_config import MAX_COUNTERS
        resp = client.get('/api/v1/editor-metadata', headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()['max_counters'] == MAX_COUNTERS

    def test_metadata_exposes_available_cities(
        self, client, auth_headers, fake_supabase,
    ):
        from src.client.client_config import AVAILABLE_CITIES
        resp = client.get('/api/v1/editor-metadata', headers=auth_headers)
        assert resp.get_json()['available_cities'] == list(AVAILABLE_CITIES)


class TestClientCity:
    """City is a plain client attribute, set on create and PUT."""

    def test_create_with_city_and_get_config(
        self, client, auth_headers, fake_supabase,
    ):
        client.post('/api/v1/client', json={
            'name': 'CityCo', 'active_slots': ['rice', 'dal'], 'city': 'chennai',
        }, headers=auth_headers)
        cfg = client.get('/api/v1/client-config/CityCo',
                         headers=auth_headers).get_json()
        assert cfg['city'] == 'Chennai'

    def test_put_updates_city(self, client, auth_headers, fake_supabase):
        cfg = client.get('/api/v1/client-config/Rippling',
                         headers=auth_headers).get_json()
        assert cfg['city'] is None
        resp = client.put('/api/v1/client-config/Rippling', json={
            'version': cfg['version'], 'city': 'NCR',
        }, headers=auth_headers)
        assert resp.status_code == 200, resp.get_json()
        after = client.get('/api/v1/client-config/Rippling',
                           headers=auth_headers).get_json()
        assert after['city'] == 'NCR'


class TestServeWeekendsApi:
    def test_weekdays_from_skips_weekend_by_default(self):
        import datetime as dt
        from api.app import _weekdays_from
        mon = dt.date(2026, 3, 23)
        days = _weekdays_from(mon, 5)
        assert [d.strftime('%a') for d in days] == ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']

    def test_weekdays_from_includes_weekend_when_enabled(self):
        import datetime as dt
        from api.app import _weekdays_from
        mon = dt.date(2026, 3, 23)
        days = _weekdays_from(mon, 7, serve_weekends=True)
        labels = [d.strftime('%a') for d in days]
        assert labels == ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

    def test_config_roundtrips_serve_weekends(self, client, auth_headers, fake_supabase):
        client.post('/api/v1/client', json={
            'name': 'WeCo', 'active_slots': ['rice', 'dal'], 'serve_weekends': True,
        }, headers=auth_headers)
        cfg = client.get('/api/v1/client-config/WeCo', headers=auth_headers).get_json()
        assert cfg['serve_weekends'] is True

    def test_put_updates_serve_weekends(self, client, auth_headers, fake_supabase):
        cfg = client.get('/api/v1/client-config/Rippling',
                         headers=auth_headers).get_json()
        assert cfg['serve_weekends'] is False
        client.put('/api/v1/client-config/Rippling', json={
            'version': cfg['version'], 'serve_weekends': True,
        }, headers=auth_headers)
        after = client.get('/api/v1/client-config/Rippling',
                           headers=auth_headers).get_json()
        assert after['serve_weekends'] is True


class TestItemCooldownConfig:
    def test_metadata_exposes_default_cooldown(self, client, auth_headers, fake_supabase):
        from src.client.client_config import DEFAULT_ITEM_COOLDOWN_DAYS
        data = client.get('/api/v1/editor-metadata', headers=auth_headers).get_json()
        assert data['default_item_cooldown_days'] == DEFAULT_ITEM_COOLDOWN_DAYS

    def test_config_roundtrips_cooldown(self, client, auth_headers, fake_supabase):
        client.post('/api/v1/client', json={
            'name': 'CoolCo', 'active_slots': ['rice', 'dal'],
            'item_cooldown_days': 14,
        }, headers=auth_headers)
        cfg = client.get('/api/v1/client-config/CoolCo', headers=auth_headers).get_json()
        assert cfg['item_cooldown_days'] == 14

    def test_put_updates_cooldown(self, client, auth_headers, fake_supabase):
        cfg = client.get('/api/v1/client-config/Rippling', headers=auth_headers).get_json()
        assert cfg['item_cooldown_days'] is None  # default
        client.put('/api/v1/client-config/Rippling', json={
            'version': cfg['version'], 'item_cooldown_days': 30,
        }, headers=auth_headers)
        after = client.get('/api/v1/client-config/Rippling', headers=auth_headers).get_json()
        assert after['item_cooldown_days'] == 30

    def test_override_rebuilds_rule_without_mutating_shared(self, fake_supabase):
        import api.app as api_app
        generic = api_app._get_menu_rules_for_city('Bangalore')
        ic = [r for r in generic
              if getattr(getattr(r, 'rule_type', None), 'value', None) == 'item_cooldown'][0]
        original = ic.cooldown_days
        new_rules = api_app._apply_item_cooldown_override(generic, 7)
        new_ic = [r for r in new_rules
                  if getattr(getattr(r, 'rule_type', None), 'value', None) == 'item_cooldown'][0]
        assert new_ic.cooldown_days == 7
        assert ic.cooldown_days == original  # shared instance untouched

    def test_override_none_is_noop(self, fake_supabase):
        import api.app as api_app
        generic = api_app._get_menu_rules_for_city('Bangalore')
        assert api_app._apply_item_cooldown_override(generic, None) is generic


class TestNonvegFlag:
    def test_plan_items_carry_is_nonveg(
        self, client, auth_headers, fake_supabase,
    ):
        data = client.post('/api/v1/plan', json={
            'client_name': 'Rippling', 'start_date': '2026-03-23',
            'num_days': 1, 'time_limit_seconds': 30,
        }, headers=auth_headers).get_json()
        items = data['solution']['2026-03-23']['items']
        assert items, "expected a populated day"
        assert all('is_nonveg' in v for v in items.values())

    def test_egg_dishes_flagged_nonveg(self, fake_supabase):
        """Egg dishes must be non-veg — including ones the ontology mislabels
        with a veg primary_protein but flags via is_egg_dish."""
        import api.app as api_app
        nonveg = api_app._get_nonveg_items()
        # protein-tagged egg dish + chicken
        assert 'kolkata_egg_curry' in nonveg
        assert 'chicken_65' in nonveg
        # egg dishes the data tags primary_protein='chana' (caught via is_egg_dish)
        assert 'anda_mirch_masala' in nonveg
        assert 'anda_ghotala' in nonveg
        # a veg peas bread must NOT be flagged
        assert 'mutter_kulcha' not in nonveg


class TestGetCounterSetup:
    """The single-read (mode, counters) accessor used by /client-config."""

    def test_single_client_setup(self, fake_supabase):
        import api.app as api_app
        loader = api_app._get_client_loader()
        mode, counters = loader.get_counter_setup('Rippling')
        assert mode == 'single'
        assert len(counters) == 1
        assert 'veg_dry' in counters[0]['categories']
        assert all('__' not in c for c in counters[0]['categories'])

    def test_multi_client_reads_stored_list(self, fake_supabase):
        import api.app as api_app
        loader = api_app._get_client_loader()
        loader.create_client(
            'Multi', counter_mode='multi',
            counters=[
                {'name': 'A', 'categories': ['rice'], 'slot_counts': {}, 'theme_map': {}},
                {'name': 'B', 'categories': ['dal'], 'slot_counts': {}, 'theme_map': {}},
            ],
        )
        mode, counters = loader.get_counter_setup('Multi')
        assert mode == 'multi'
        assert [c['name'] for c in counters] == ['A', 'B']

    def test_classic_create_stores_single_counter(self, fake_supabase):
        import api.app as api_app
        loader = api_app._get_client_loader()
        loader.create_client('Plain', ['rice', 'dal'])
        # Classic create stores a one-element counters list (the config's only
        # home now — no legacy tables).
        rows = [r for r in fake_supabase.rows('clients') if r['name'] == 'Plain']
        assert rows and len(rows[0]['counters']) == 1
        assert set(rows[0]['counters'][0]['categories']) == {'rice', 'dal'}
        mode, counters = loader.get_counter_setup('Plain')
        assert mode == 'single'
        assert set(counters[0]['categories']) == {'rice', 'dal'}


class TestCounterClientEndpoints:
    """End-to-end coverage for the single/multi cuisine-counter flow through
    the create + client-config endpoints (backed by FakeSupabase)."""

    def test_existing_client_reports_single_counter(
        self, client, auth_headers, fake_supabase,
    ):
        # Rippling is seeded with a single counter in clients.counters.
        resp = client.get('/api/v1/client-config/Rippling', headers=auth_headers)
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['counter_mode'] == 'single'
        assert len(body['counters']) == 1
        primary = body['counters'][0]
        assert 'veg_dry' in primary['categories']

    def test_create_multi_counter_client_then_read_back(
        self, client, auth_headers, fake_supabase,
    ):
        payload = {
            'name': 'Acme',
            'counter_mode': 'multi',
            'counters': [
                {
                    'name': 'North Counter',
                    'categories': ['bread', 'veg_gravy', 'rice'],
                    'slot_counts': {'veg_gravy': 2},
                    'theme_map': {'monday': 'north'},
                },
                {
                    'name': 'Chinese Counter',
                    'categories': ['starter', 'veg_dry'],
                    'slot_counts': {'veg_dry': 3},
                    'theme_map': {'tuesday': 'chinese'},
                },
            ],
        }
        resp = client.post('/api/v1/client', json=payload, headers=auth_headers)
        assert resp.status_code == 200, resp.get_json()

        # Client now shows up in the list.
        listing = client.get('/api/v1/clients', headers=auth_headers).get_json()
        assert 'Acme' in listing['clients']

        cfg = client.get('/api/v1/client-config/Acme', headers=auth_headers).get_json()
        assert cfg['counter_mode'] == 'multi'
        assert [c['name'] for c in cfg['counters']] == ['North Counter', 'Chinese Counter']
        assert cfg['counters'][0]['categories'] == ['bread', 'veg_gravy', 'rice']
        assert cfg['counters'][0]['slot_counts']['veg_gravy'] == 2
        assert cfg['counters'][1]['slot_counts']['veg_dry'] == 3

        # The flat fields the editor consumes come from the primary counter,
        # so the solver (which reads the primary) plans the same config.
        assert cfg['slot_counts'].get('veg_gravy') == 2
        assert cfg['theme_map']['monday'] == 'north'
        # Counters are persisted in the clients.counters JSONB column — no
        # separate table.
        acme = [r for r in fake_supabase.rows('clients') if r['name'] == 'Acme'][0]
        assert len(acme['counters']) == 2
        assert [c['name'] for c in acme['counters']] == ['North Counter', 'Chinese Counter']

    def test_create_rejects_counter_without_categories(
        self, client, auth_headers, fake_supabase,
    ):
        resp = client.post('/api/v1/client', json={
            'name': 'BadClient',
            'counter_mode': 'multi',
            'counters': [
                {'name': 'Empty', 'categories': [], 'slot_counts': {}, 'theme_map': {}},
            ],
        }, headers=auth_headers)
        assert resp.status_code == 400
        assert 'category' in resp.get_json()['error'].lower()
        # Nothing should have been created.
        assert 'BadClient' not in client.get(
            '/api/v1/clients', headers=auth_headers,
        ).get_json()['clients']

    def test_create_rejects_too_many_counters(
        self, client, auth_headers, fake_supabase,
    ):
        from src.client.client_config import MAX_COUNTERS
        counters = [
            {'name': f'C{i}', 'categories': ['rice'], 'slot_counts': {}, 'theme_map': {}}
            for i in range(MAX_COUNTERS + 1)
        ]
        resp = client.post('/api/v1/client', json={
            'name': 'TooMany', 'counter_mode': 'multi', 'counters': counters,
        }, headers=auth_headers)
        assert resp.status_code == 400

    def test_create_rejects_unknown_pool_without_creating_the_client(
        self, client, auth_headers, fake_supabase,
    ):
        """A bad ``source_pools`` token must not leave a client behind.

        ``source_pools`` used to be validated *after* create_client() had
        committed the row: the caller got 400 while a real client existed with
        no pools, and retrying with a corrected payload then failed on the
        duplicate name. Validation now happens before the insert.
        """
        resp = client.post('/api/v1/client', json={
            'name': 'Orphan',
            'active_slots': ['rice', 'dal'],
            'source_pools': ['definitely_not_a_pool'],
        }, headers=auth_headers)
        assert resp.status_code == 400
        assert 'pool' in resp.get_json()['error'].lower()
        # Nothing was created — the retry path stays open.
        assert 'Orphan' not in client.get(
            '/api/v1/clients', headers=auth_headers,
        ).get_json()['clients']
        assert not [r for r in fake_supabase.rows('clients')
                    if r['name'] == 'Orphan']

    def test_create_rejects_bad_working_days_without_creating_the_client(
        self, client, auth_headers, fake_supabase,
    ):
        resp = client.post('/api/v1/client', json={
            'name': 'Orphan2',
            'active_slots': ['rice'],
            'working_days': ['funday'],
        }, headers=auth_headers)
        assert resp.status_code == 400
        assert not [r for r in fake_supabase.rows('clients')
                    if r['name'] == 'Orphan2']

    def test_create_persists_pools_and_working_days_in_one_write(
        self, client, auth_headers, fake_supabase,
    ):
        """Valid optional columns land on the created row directly."""
        resp = client.post('/api/v1/client', json={
            'name': 'Quince2',
            'active_slots': ['rice', 'dal'],
            'working_days': ['Wed', 'thursday', 'FRI'],
            'source_pools': ['common', 'icon'],
            'item_cooldown_days': 7,
        }, headers=auth_headers)
        assert resp.status_code == 200, resp.get_json()
        row = [r for r in fake_supabase.rows('clients')
               if r['name'] == 'Quince2'][0]
        assert row['working_days'] == ['wednesday', 'thursday', 'friday']
        # 'common' is implicit and never stored.
        assert row['source_pools'] == ['icon']
        assert row['item_cooldown_days'] == 7

    def test_create_rejects_negative_cooldown(
        self, client, auth_headers, fake_supabase,
    ):
        resp = client.post('/api/v1/client', json={
            'name': 'Orphan3', 'active_slots': ['rice'],
            'item_cooldown_days': -3,
        }, headers=auth_headers)
        assert resp.status_code == 400
        assert not [r for r in fake_supabase.rows('clients')
                    if r['name'] == 'Orphan3']

    def test_classic_create_defaults_to_single(
        self, client, auth_headers, fake_supabase,
    ):
        resp = client.post('/api/v1/client', json={
            'name': 'Legacy', 'active_slots': ['rice', 'dal', 'veg_dry'],
        }, headers=auth_headers)
        assert resp.status_code == 200
        cfg = client.get('/api/v1/client-config/Legacy', headers=auth_headers).get_json()
        assert cfg['counter_mode'] == 'single'
        assert len(cfg['counters']) == 1
        assert set(cfg['counters'][0]['categories']) == {'rice', 'dal', 'veg_dry'}

    def test_put_switches_single_to_multi(
        self, client, auth_headers, fake_supabase,
    ):
        # Start from the seeded single-counter Rippling, fetch its version.
        cfg = client.get('/api/v1/client-config/Rippling', headers=auth_headers).get_json()
        version = cfg['version']

        resp = client.put('/api/v1/client-config/Rippling', json={
            'version': version,
            'counter_mode': 'multi',
            'counters': [
                {'name': 'Main', 'categories': ['rice', 'dal'],
                 'slot_counts': {'rice': 2}, 'theme_map': {'friday': 'north'}},
                {'name': 'Live', 'categories': ['starter'],
                 'slot_counts': {}, 'theme_map': {}},
            ],
        }, headers=auth_headers)
        assert resp.status_code == 200, resp.get_json()

        updated = client.get('/api/v1/client-config/Rippling', headers=auth_headers).get_json()
        assert updated['counter_mode'] == 'multi'
        assert [c['name'] for c in updated['counters']] == ['Main', 'Live']
        assert updated['counters'][0]['slot_counts']['rice'] == 2
        # Version bumped by the PUT.
        assert updated['version'] == version + 1

    def test_put_single_mode_keeps_only_primary_counter(
        self, client, auth_headers, fake_supabase,
    ):
        cfg = client.get('/api/v1/client-config/Rippling', headers=auth_headers).get_json()
        resp = client.put('/api/v1/client-config/Rippling', json={
            'version': cfg['version'],
            'counter_mode': 'single',
            'counters': [
                {'name': 'Only', 'categories': ['rice'], 'slot_counts': {}, 'theme_map': {}},
                {'name': 'Dropped', 'categories': ['dal'], 'slot_counts': {}, 'theme_map': {}},
            ],
        }, headers=auth_headers)
        assert resp.status_code == 200
        updated = client.get('/api/v1/client-config/Rippling', headers=auth_headers).get_json()
        assert updated['counter_mode'] == 'single'
        assert len(updated['counters']) == 1
        # Single mode drops the extra counter and keeps only the primary,
        # read back from the legacy tables (categories preserved; the single
        # counter's name is cosmetic and not persisted separately).
        assert updated['counters'][0]['categories'] == ['rice']
        # Single mode stores exactly one counter in clients.counters.
        rip = [r for r in fake_supabase.rows('clients') if r['name'] == 'Rippling'][0]
        assert len(rip['counters']) == 1
