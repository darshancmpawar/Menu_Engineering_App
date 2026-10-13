"""DB-backed `shared_categories` (the editor's cross-counter toggle+multiselect).

The base slots a client serves identically across counters are stored on
``clients.shared_categories`` and edited via the API. A client configured only
in ``client_rules.json`` (e.g. DXC) has none in the DB, so GET falls back to the
file value — the planner consumes whichever wins.
"""

from __future__ import annotations

import pytest

flask = pytest.importorskip("flask", reason="Flask not installed")

from tests.fake_supabase import FakeSupabase


def _seed():
    return {
        'clients': [
            {'name': 'MultiCo', 'version': 1, 'city': 'Bangalore',
             'counters': [
                 {'name': 'Veg', 'categories': ['bread', 'rice', 'veg_gravy'],
                  'slot_counts': {'bread': 1, 'rice': 1, 'veg_gravy': 1},
                  'theme_map': {}},
                 {'name': 'NonVeg', 'categories': ['bread', 'rice', 'nonveg_main'],
                  'slot_counts': {'bread': 1, 'rice': 1, 'nonveg_main': 1},
                  'theme_map': {}}]},
        ],
        'app_settings': [], 'menu_history': [], 'week_signatures': [],
    }


@pytest.fixture
def loader(monkeypatch):
    import src.db as db_mod
    monkeypatch.setattr(db_mod, '_sb_client', FakeSupabase(seed=_seed()),
                        raising=False)
    from src.client.client_config import ClientConfigLoader
    return ClientConfigLoader()


@pytest.fixture
def api(monkeypatch):
    import src.db as db_mod
    monkeypatch.setattr(db_mod, '_sb_client', FakeSupabase(seed=_seed()),
                        raising=False)
    import api.app as api_app
    monkeypatch.setattr(api_app, '_client_loader', None, raising=False)
    api_app.reset_caches()
    api_app.app.config['TESTING'] = True
    return api_app


def _c(api):
    from api.rate_limit import reset_for_tests
    reset_for_tests()
    return api.app.test_client()


# --- config layer ----------------------------------------------------------

class TestConfigLayer:
    def test_unset_reads_empty(self, loader):
        assert loader.get_client_shared_categories('MultiCo') == []

    def test_set_normalises_and_dedupes(self, loader):
        loader.set_client_shared_categories(
            'MultiCo', ['bread', 'rice', 'bogus_slot', 'BREAD'])
        assert loader.get_client_shared_categories('MultiCo') == ['bread', 'rice']

    def test_get_client_row_carries_it(self, loader):
        loader.set_client_shared_categories('MultiCo', ['rice'])
        assert loader.get_client_row('MultiCo')['shared_categories'] == ['rice']

    def test_create_with_shared_categories(self, loader):
        loader.create_client(
            'NewCo', counter_mode='multi',
            counters=[
                {'name': 'A', 'categories': ['bread', 'rice'],
                 'slot_counts': {'bread': 1, 'rice': 1}, 'theme_map': {}},
                {'name': 'B', 'categories': ['bread', 'rice'],
                 'slot_counts': {'bread': 1, 'rice': 1}, 'theme_map': {}}],
            shared_categories=['bread', 'nope'])
        assert loader.get_client_shared_categories('NewCo') == ['bread']

    def test_atomic_update_carries_it(self, loader):
        v = loader.get_client_row('MultiCo')['version']
        loader.update_client_atomic(
            'MultiCo', v, {'shared_categories': ['bread', 'rice']})
        assert loader.get_client_shared_categories('MultiCo') == ['bread', 'rice']


# --- API -------------------------------------------------------------------

class TestApi:
    def test_get_exposes_it(self, api):
        body = _c(api).get('/api/v1/client-config/MultiCo').get_json()
        assert body['shared_categories'] == []

    def test_put_sets_it(self, api):
        ver = _c(api).get('/api/v1/client-config/MultiCo').get_json()['version']
        r = _c(api).put('/api/v1/client-config/MultiCo',
                        json={'version': ver, 'shared_categories': ['bread']})
        assert r.status_code == 200
        got = _c(api).get('/api/v1/client-config/MultiCo').get_json()
        assert got['shared_categories'] == ['bread']

    def test_an_unrecognised_category_is_refused_not_dropped(self, api):
        """This sent `['bread', 'x']` and asserted `['bread']` came back — the
        junk token silently discarded, which is note 9's config mismatch and
        exactly what `_validated_region_map` beside it refuses to do: storing
        the survivors leaves the operator believing they saved something they
        did not. The write now says which name it did not recognise."""
        ver = _c(api).get('/api/v1/client-config/MultiCo').get_json()['version']
        r = _c(api).put('/api/v1/client-config/MultiCo',
                        json={'version': ver, 'shared_categories': ['bread', 'x']})
        assert r.status_code == 400, r.get_json()
        assert "'x'" in r.get_json()['error'], r.get_json()['error']
        # and nothing is stored from a rejected write
        assert _c(api).get(
            '/api/v1/client-config/MultiCo').get_json()['shared_categories'] == []

    def test_post_creates_with_it(self, api):
        r = _c(api).post('/api/v1/client', json={
            'name': 'PostCo', 'city': 'Bangalore', 'counter_mode': 'multi',
            'counters': [
                {'name': 'A', 'categories': ['bread', 'rice'],
                 'slot_counts': {'bread': 1, 'rice': 1}, 'theme_map': {}},
                {'name': 'B', 'categories': ['bread', 'rice'],
                 'slot_counts': {'bread': 1, 'rice': 1}, 'theme_map': {}}],
            'shared_categories': ['rice']})
        assert r.status_code == 200, r.get_json()
        got = _c(api).get('/api/v1/client-config/PostCo').get_json()
        assert got['shared_categories'] == ['rice']

    def test_falls_back_to_file_when_db_empty(self, api):
        # DXC has no DB shared_categories here, but client_rules.json does — the
        # endpoint must surface the file value so the planner still syncs.
        import src.db as db_mod
        # seed DXC as a bare client so the DB value is empty.
        db_mod._sb_client.seed('clients', [{
            'name': 'DXC', 'version': 1, 'city': 'Bangalore',
            'counters': [{'name': 'Veg Lunch', 'categories': ['bread', 'rice'],
                          'slot_counts': {'bread': 1, 'rice': 1}, 'theme_map': {}},
                         {'name': 'Non Veg Lunch', 'categories': ['bread', 'rice'],
                          'slot_counts': {'bread': 1, 'rice': 1}, 'theme_map': {}}]}])
        body = _c(api).get('/api/v1/client-config/DXC').get_json()
        assert 'bread' in body['shared_categories']
        assert 'rice' in body['shared_categories']


class TestTheWriteRejectsASlotThePrimaryCounterDoesNotServe:
    """A shared category is taken from the PRIMARY counter's menu, so naming a
    slot it does not serve shares nothing at all.

    Waters is the case: `shared_categories: ['nonveg_main']` on a site whose
    primary counter is the Roti VEG Combo. Zero shared items were extracted
    across a four-counter client — two of which serve non-veg and could have
    been synced — and nothing said so. The toggle is on, the multiselect lists
    the category, and the counters go on serving whatever they like.

    Rejected at the write for the same reason `region_map` is: a stored value
    matching nothing is note 9's silent config mismatch.
    """

    def _version(self, api, name='MultiCo'):
        return _c(api).get(f'/api/v1/client-config/{name}').get_json()['version']

    def test_a_slot_the_primary_lacks_is_refused(self, api):
        r = _c(api).put('/api/v1/client-config/MultiCo', json={
            'shared_categories': ['nonveg_main'],
            'version': self._version(api)})
        assert r.status_code == 400, r.get_json()
        err = r.get_json()['error']
        # The message has to name the slot, the counter and a way out.
        assert 'nonveg_main' in err and 'Veg' in err, err
        assert 'bread' in err, 'the message should say what IS servable'

    def test_a_slot_the_primary_serves_is_accepted(self, api):
        r = _c(api).put('/api/v1/client-config/MultiCo', json={
            'shared_categories': ['bread', 'rice'],
            'version': self._version(api)})
        assert r.status_code == 200, r.get_json()
        got = _c(api).get('/api/v1/client-config/MultiCo').get_json()
        assert got['shared_categories'] == ['bread', 'rice']

    def test_clearing_is_always_allowed(self, api):
        """`[]` is how sharing is switched off — it can never be invalid."""
        r = _c(api).put('/api/v1/client-config/MultiCo', json={
            'shared_categories': [], 'version': self._version(api)})
        assert r.status_code == 200, r.get_json()

    def test_it_reads_the_counters_from_the_SAME_payload(self, api):
        """A counter change and a sharing change arrive in one PUT, so the
        check must run against the counters the client will HAVE — not the
        stored ones. Here the primary gains `nonveg_main` in the same write
        that shares it, which must therefore be allowed."""
        r = _c(api).put('/api/v1/client-config/MultiCo', json={
            'counter_mode': 'multi',
            'counters': [
                {'name': 'Veg', 'categories': ['bread', 'rice', 'nonveg_main'],
                 'slot_counts': {'bread': 1, 'rice': 1, 'nonveg_main': 1},
                 'theme_map': {}},
                {'name': 'NonVeg', 'categories': ['bread', 'nonveg_main'],
                 'slot_counts': {'bread': 1, 'nonveg_main': 1},
                 'theme_map': {}}],
            'shared_categories': ['nonveg_main'],
            'version': self._version(api)})
        assert r.status_code == 200, r.get_json()

    def test_create_refuses_a_slot_the_primary_counter_lacks(self, api):
        """The create path had no validation at all, so a client could be born
        sharing a category nothing would ever supply."""
        r = _c(api).post('/api/v1/client', json={
            'name': 'BornBroken', 'city': 'Bangalore', 'counter_mode': 'multi',
            'counters': [
                {'name': 'Veg', 'categories': ['bread', 'rice'],
                 'slot_counts': {'bread': 1, 'rice': 1}, 'theme_map': {}},
                {'name': 'NonVeg', 'categories': ['bread', 'nonveg_main'],
                 'slot_counts': {'bread': 1, 'nonveg_main': 1}, 'theme_map': {}}],
            'shared_categories': ['nonveg_main']})
        assert r.status_code == 400, r.get_json()
        assert 'nonveg_main' in r.get_json()['error']
        # and the client is not left behind half-created
        assert _c(api).get('/api/v1/client-config/BornBroken').status_code == 404


# --- end to end: the feature's actual promise -------------------------------

@pytest.fixture
def live_api(monkeypatch):
    """The real client rows, so this tests the fleet's own configs."""
    import src.db as db_mod
    from tests.client_fixtures import APP_SETTINGS, CLIENTS
    monkeypatch.setattr(db_mod, '_sb_client', FakeSupabase(seed={
        'clients': [dict(c) for c in CLIENTS],
        'app_settings': [dict(s) for s in APP_SETTINGS],
        'menu_history': [], 'week_signatures': [],
    }), raising=False)
    import api.app as api_app
    monkeypatch.setattr(api_app, '_client_loader', None, raising=False)
    api_app.reset_caches()
    api_app.app.config['TESTING'] = True
    return api_app


@pytest.mark.slow
def test_every_unsynced_shared_cell_is_reported(live_api):
    """The promise is NOT "the counters always match" — that is false by
    design. A pinned dish can be ineligible on a sibling counter, and the right
    answer is to serve something else rather than fail the menu.

    The promise is that a divergence is never SILENT. Every shared cell that
    comes back different must be accounted for by one of the two channels:

      * `pool_warnings` — the whole-sync fallback in `api/app.py`, which drops
        every shared pin when the counter cannot be solved with them;
      * a `*_pin` relaxation — one cell's pin dropped in `_build_cells`.

    Before the relaxation was stamped this test failed on World Bank: one veg
    gravy diverged and both channels were empty. That is the case it exists for
    — all nine other cells matching made the gap easy to miss.
    """
    from ui.formatters import shared_items_from_solution
    from src.solver._helpers import strip_color_suffix as strip
    from tests.client_fixtures import CLIENTS

    row = next(c for c in CLIENTS if c['name'] == 'World Bank')
    shared = row.get('shared_categories') or []
    assert shared, 'fixture no longer shares anything'

    def _plan(idx, items=None):
        body = {'client_name': 'World Bank', 'counter_index': idx,
                'start_date': '2026-08-03', 'num_days': 5}
        if items is not None:
            body['shared_items'] = items
        r = _c(live_api).post('/api/v1/plan', json=body)
        assert r.status_code == 200, r.get_json()
        return r.get_json()

    primary = _plan(0)
    items = shared_items_from_solution(primary['solution'], shared)
    assert items, 'nothing was extracted to share'

    second = _plan(1, items)

    def _dish(sol, iso, sid):
        cell = (sol.get(iso, {}).get('items') or {}).get(sid)
        return strip(str(cell.get('item') if isinstance(cell, dict) else cell or ''))

    diverged = [
        (iso, sid)
        for iso, day in second['solution'].items()
        for sid in (day.get('items') or {})
        if sid.split('__')[0] in shared
        and _dish(second['solution'], iso, sid)
        and _dish(primary['solution'], iso, sid)
        and _dish(second['solution'], iso, sid)
        != _dish(primary['solution'], iso, sid)
    ]
    if not diverged:
        return                                  # fully synced: nothing to explain

    reported = bool(second.get('pool_warnings')) or any(
        str(r.get('rule', '')).endswith('_pin')
        for r in (second.get('relaxations') or [])
    )
    assert reported, (
        f'{len(diverged)} shared cell(s) diverged with nothing explaining it: '
        f'{diverged[:5]}'
    )
