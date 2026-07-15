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
            "Schema drift" in rec.message and "scripts/create_tables.sql" in rec.message
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
        assert [r['item_base'] for r in rows] == ['jeera_rice']

        second = client.post('/api/v1/save', json={
            'client_name': 'Rippling',
            'week_plan': {'2026-03-23': {'rice': 'lemon_rice(Y)'}},
            'week_start': '2026-03-23',
        }, headers=auth_headers)
        assert second.status_code == 200
        rows = fake_supabase.rows('menu_history')
        assert [r['item_base'] for r in rows] == ['lemon_rice']
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


class TestEditorMetadataCounters:
    def test_metadata_exposes_max_counters(
        self, client, auth_headers, fake_supabase,
    ):
        from src.client.client_config import MAX_COUNTERS
        resp = client.get('/api/v1/editor-metadata', headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()['max_counters'] == MAX_COUNTERS


class TestCounterClientEndpoints:
    """End-to-end coverage for the single/multi cuisine-counter flow through
    the create + client-config endpoints (backed by FakeSupabase)."""

    def test_existing_client_reports_single_counter(
        self, client, auth_headers, fake_supabase,
    ):
        # Rippling is seeded with the classic single-counter storage; add a
        # veg_dry x2 override so we can prove it surfaces in the synthesised
        # counter's frequency.
        fake_supabase.seed('slot_count_overrides', [
            {'client_name': 'Rippling', 'slot': 'veg_dry', 'count': 2},
        ])
        resp = client.get('/api/v1/client-config/Rippling', headers=auth_headers)
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['counter_mode'] == 'single'
        assert len(body['counters']) == 1
        primary = body['counters'][0]
        assert 'veg_dry' in primary['categories']
        assert primary['slot_counts'].get('veg_dry') == 2

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

        # Primary counter is mirrored into the legacy tables so the solver
        # keeps working: config's top-level slot_counts/theme_map reflect it.
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
        # Nothing is stored in the clients.counters column for a single client.
        rip = [r for r in fake_supabase.rows('clients') if r['name'] == 'Rippling'][0]
        assert rip['counters'] == []
