"""Pune, through the whole stack: every endpoint, then the UI layer.

The other Pune files test the pieces — `test_city_ontology` the ontology
resolution, `test_pune_rules` the ruleset, `test_pune_plan` the city rules end to
end, `test_pune_client_logic` the client's sample week. This one walks the paths a
real user takes and that none of those cover:

* `/save` then `/plan` again — the item cooldown reading history the API wrote,
  rather than a hand-seeded `menu_history`. That is where "week 2 has no bread"
  would actually have surfaced.
* `/regenerate` on a Pune counter, including that a restricted slot stays absent.
* `/saved-plan`, which enriches from the ontology and so has to pick the city's.
* The Streamlit-side rendering: display labels, the red-dish tagging, and the
  Excel export.

Kept out of `-m slow` because the Pune counter solves in well under a second.
"""

import os

import pytest

from tests.fake_supabase import FakeSupabase

MONDAY = '2026-08-03'
NEXT_MONDAY = '2026-08-10'
TIME_LIMIT = 60
CLIENT = 'Amadeus Pune'


@pytest.fixture
def pune_api(monkeypatch):
    """The live Amadeus Pune row, on an empty history."""
    import src.db as db_mod
    import api.app as api_app
    from tests.client_fixtures import CLIENTS

    row = next(dict(c) for c in CLIENTS if c['name'] == CLIENT)
    fake = FakeSupabase(seed={
        'clients': [row], 'app_settings': [],
        'menu_history': [], 'week_signatures': [],
    })
    monkeypatch.setattr(db_mod, '_sb_client', fake, raising=False)
    monkeypatch.setattr(api_app, '_client_loader', None, raising=False)
    api_app.reset_caches()
    api_app.app.config['TESTING'] = True
    return api_app


def _post(api_app, path, body):
    from api.rate_limit import reset_for_tests
    reset_for_tests()
    return api_app.app.test_client().post(path, json=body)


def _get(api_app, path):
    from api.rate_limit import reset_for_tests
    reset_for_tests()
    return api_app.app.test_client().get(path)


def _plan(api_app, start=MONDAY, days=7):
    r = _post(api_app, '/api/v1/plan', {
        'client_name': CLIENT, 'start_date': start,
        'num_days': days, 'time_limit_seconds': TIME_LIMIT,
    })
    body = r.get_json() or {}
    assert r.status_code == 200, body.get('error') or body.get('message')
    return body


def _week_plan(solution):
    """The `/save` payload shape: {date: {slot: item}}."""
    return {
        d: {s: e['item_base'] for s, e in day['items'].items()}
        for d, day in solution.items()
    }


class TestEveryEndpointServesAPuneClient:
    @pytest.mark.parametrize('path', [
        '/api/v1/clients',
        '/api/v1/health',
        '/api/v1/editor-metadata',
        '/api/v1/editor-metadata?city=Pune',
        f'/api/v1/client-config/{CLIENT.replace(" ", "%20")}',
        f'/api/v1/saved-plan?client_name={CLIENT.replace(" ", "%20")}'
        f'&start_date={MONDAY}&num_days=7',
    ])
    def test_get_endpoint(self, pune_api, path):
        r = _get(pune_api, path)
        assert r.status_code == 200, (path, r.status_code, r.get_json())

    @pytest.mark.parametrize('path,body', [
        ('/api/v1/pool-preview', {'source_pools': [], 'city': 'Pune'}),
        ('/api/v1/diagnose',
         {'client_name': CLIENT, 'start_date': MONDAY, 'num_days': 7}),
        ('/api/v1/plan',
         {'client_name': CLIENT, 'start_date': MONDAY, 'num_days': 7,
          'time_limit_seconds': TIME_LIMIT}),
    ])
    def test_post_endpoint(self, pune_api, path, body):
        r = _post(pune_api, path, body)
        assert r.status_code == 200, (path, r.status_code, r.get_json())

    def test_pool_preview_counts_the_pune_list(self, pune_api):
        r = _post(pune_api, '/api/v1/pool-preview',
                  {'source_pools': [], 'city': 'Pune'})
        body = r.get_json()
        assert body['eligible_item_count'] == 272, body
        assert body['city'] == 'Pune'

    def test_pool_preview_without_a_city_counts_the_default(self, pune_api):
        r = _post(pune_api, '/api/v1/pool-preview', {'source_pools': []})
        assert r.get_json()['eligible_item_count'] > 272

    def test_bangalore_pool_token_is_rejected_for_a_pune_client(self, pune_api):
        """Pool tokens live inside one city's list, so a Bangalore token on a Pune
        client would match nothing and silently serve `common` alone."""
        r = pune_api.app.test_client().put(
            f'/api/v1/client-config/{CLIENT.replace(" ", "%20")}',
            json={'version': 1, 'source_pools': ['infineon']})
        assert r.status_code == 400
        assert 'Pune' in r.get_json()['error']


class TestSaveThenReplan:
    """The cooldown reading history the API itself wrote.

    Pune's bread pool is two dishes and its welcome drink is one, both declared
    staples — if the exemption did not reach the cooldown, week 2 would have no
    bread and no drink. Seeding `menu_history` by hand (as test_pune_plan does)
    exercises the same rule but not the save path that produces those rows.
    """

    def test_second_week_after_a_real_save(self, pune_api):
        week1 = _plan(pune_api, MONDAY)['solution']
        r = _post(pune_api, '/api/v1/save', {
            'client_name': CLIENT, 'week_start': MONDAY,
            'week_plan': _week_plan(week1),
        })
        assert r.status_code == 200, r.get_json()

        week2 = _plan(pune_api, NEXT_MONDAY)['solution']

        def by_slot(sol, slot):
            return {d['items'][slot]['item_base']
                    for d in sol.values() if slot in d['items']}

        assert by_slot(week2, 'bread') == {'chapati'}
        assert by_slot(week2, 'welcome_drink') == {'buttermilk'}
        # Non-staples must NOT come back — the exemption is scoped, not a blanket
        # cooldown switch-off.
        assert not (by_slot(week1, 'dal') & by_slot(week2, 'dal'))
        assert not (by_slot(week1, 'veg_gravy') & by_slot(week2, 'veg_gravy'))

    def test_saved_plan_reads_back_from_the_pune_list(self, pune_api):
        week1 = _plan(pune_api, MONDAY)['solution']
        _post(pune_api, '/api/v1/save', {
            'client_name': CLIENT, 'week_start': MONDAY,
            'week_plan': _week_plan(week1),
        })
        r = _get(pune_api,
                 f'/api/v1/saved-plan?client_name={CLIENT.replace(" ", "%20")}'
                 f'&start_date={MONDAY}&num_days=7')
        body = r.get_json()
        assert r.status_code == 200 and body['exists'] is True, body
        # `_enrich_history_plan` adds the colour suffix from the ontology, so it
        # has to be reading Pune's — a Bangalore lookup would leave dishes bare.
        assert set(body['solution']) == set(week1)


class TestRegenerate:
    def test_one_cell_changes_and_the_rest_hold(self, pune_api):
        week = _week_plan(_plan(pune_api, MONDAY)['solution'])
        target = '2026-08-05'    # a Wednesday, full menu
        r = _post(pune_api, '/api/v1/regenerate', {
            'client_name': CLIENT, 'start_date': MONDAY, 'num_days': 7,
            'time_limit_seconds': TIME_LIMIT, 'base_plan': week,
            'replace_slots': {target: ['veg_gravy']},
        })
        assert r.status_code == 200, r.get_json()
        out = r.get_json()['solution']
        assert (out[target]['items']['veg_gravy']['item_base']
                != week[target]['veg_gravy'])
        assert (out['2026-08-04']['items']['veg_gravy']['item_base']
                == week['2026-08-04']['veg_gravy'])

    def test_restricted_slots_stay_absent_through_regenerate(self, pune_api):
        """A day restriction is skip_cells, and the regenerator has its own cell
        builder — Sunday must not sprout a gravy on the way back."""
        week = _week_plan(_plan(pune_api, MONDAY)['solution'])
        r = _post(pune_api, '/api/v1/regenerate', {
            'client_name': CLIENT, 'start_date': MONDAY, 'num_days': 7,
            'time_limit_seconds': TIME_LIMIT, 'base_plan': week,
            'replace_slots': {'2026-08-09': ['dessert']},
        })
        assert r.status_code == 200, r.get_json()
        sunday = r.get_json()['solution']['2026-08-09']['items']
        assert set(sunday) == {
            'rice', 'curd_side', 'papad', 'welcome_drink', 'dessert'}


class TestStreamlitLayerRendersAPuneMenu:
    @pytest.fixture
    def solution(self, pune_api):
        return _plan(pune_api, MONDAY)['solution']

    def test_every_slot_has_a_label_and_a_rank(self, solution):
        from src.constants import DISPLAY_SLOT_ORDER
        from ui.formatters import display_label_for_slot_id
        slots = {s for day in solution.values() for s in day['items']}
        assert 'curd_side' in slots
        for s in slots:
            assert display_label_for_slot_id(s), s
            assert s.split('__')[0] in DISPLAY_SLOT_ORDER, s

    def test_nothing_is_tagged_non_veg(self, solution):
        """The Pune list is all vegetarian, so no dish may render red."""
        from ui.formatters import nonveg_slots_from_solution
        by_date = nonveg_slots_from_solution(solution)
        assert not any(by_date.values()), by_date

    def test_the_sunday_raita_is_a_solved_dish_with_a_colour(self, solution):
        """A solved dish carries a `(colour)` suffix; a stamped constant cannot.
        This is the observable difference the curd_side config bought."""
        from src.solver._helpers import strip_color_suffix
        sunday = solution['2026-08-09']['items']
        raita = sunday['curd_side']['item']
        assert strip_color_suffix(raita) != raita, raita
        assert sunday['papad']['item'] == 'Papad'   # a constant, no suffix

    def test_excel_export_builds(self, solution):
        import sys
        import types
        # planner_view imports streamlit at module scope for the table helpers.
        sys.modules.setdefault('streamlit', types.ModuleType('streamlit'))
        from ui.planner_view import download_filename, flatten_result, plan_xlsx
        blocks = [{'name': 'Counter 1', **flatten_result({'solution': solution})}]
        data = plan_xlsx(blocks, CLIENT)
        assert isinstance(data, (bytes, bytearray)) and len(data) > 1000
        assert 'amadeus' in download_filename(blocks, CLIENT).lower()


class TestPerCityIsolation:
    """The two cities must not leak into each other at any layer."""

    def test_ontology_caches_are_shared_by_path_not_city(self, pune_api):
        pune_api.reset_caches()
        blr, _ = pune_api._get_menu_data('Bangalore')
        # Hyderabad, not Chennai: Chennai has its own workbook now, so it is a
        # separate entry rather than a second reference to Bangalore's.
        hyd, _ = pune_api._get_menu_data('Hyderabad')
        pune, _ = pune_api._get_menu_data('Pune')
        assert blr is hyd                           # same file, one load
        assert pune is not blr and len(pune) == 272
        assert pune_api._ontology.cache_sizes()['menu_data'] == 2

    def test_rulesets_do_not_bleed(self):
        from src.menu_rules.menu_rule_loader import MenuRuleLoader
        blr = {r.name for r in MenuRuleLoader().load_for_city('Bangalore')}
        pune = {r.name for r in MenuRuleLoader().load_for_city('Pune')}
        assert 'nonveg_biryani_once_per_week' in blr
        assert 'nonveg_biryani_once_per_week' not in pune
        assert 'plain_chapati_may_repeat' in pune
        assert 'plain_chapati_may_repeat' not in blr

    def test_client_rules_are_scoped_to_their_client(self):
        from src.menu_rules.menu_rule_loader import MenuRuleLoader
        loader = MenuRuleLoader()
        blr = loader.load_for_city('Bangalore')
        # 'Amadeus' (Bangalore) and 'Amadeus Pune' are different clients whose
        # names share a prefix — a substring match would cross-contaminate them.
        amadeus = {r.name for r in loader.load_for_client('Amadeus', blr, 'North')}
        assert not any(n.startswith('amadeus_pune_') for n in amadeus), amadeus

    def test_nonveg_name_set_is_per_city(self, pune_api):
        assert pune_api._get_nonveg_items('Pune') == set()
        assert len(pune_api._get_nonveg_items('Bangalore')) > 0

    def test_pin_resolution_is_per_city(self, pune_api):
        blr = pune_api._ontology_item_names('Bangalore')
        pune = pune_api._ontology_item_names('Pune')
        assert 'chicken_biryani' in blr and 'chicken_biryani' not in pune
        assert 'phodnicha_bhat' in pune and 'phodnicha_bhat' not in blr

class TestNoCrossCityWorkbookReads:
    """The strongest form of "city integration is done properly": instrument the
    ONE place a workbook is opened and assert a Pune request never touches
    Bangalore's file, nor the reverse.

    Inspecting call sites proves the code I looked at; this proves the code that
    runs. A helper that quietly defaults to the Bangalore path shows up here and
    nowhere else.
    """

    @pytest.fixture
    def traced(self, monkeypatch):
        import src.preprocessor.excel_reader as er
        reads = []
        original = er.ExcelReader.read

        def record(self):
            reads.append(os.path.basename(str(self.file_path)))
            return original(self)

        monkeypatch.setattr(er.ExcelReader, 'read', record)
        return reads

    @pytest.fixture
    def fleet_api(self, monkeypatch):
        """Every client, so a request can pick either city."""
        import src.db as db_mod
        import api.app as api_app
        from tests.client_fixtures import APP_SETTINGS, CLIENTS

        fake = FakeSupabase(seed={
            'clients': [dict(c) for c in CLIENTS],
            'app_settings': [dict(s) for s in APP_SETTINGS],
            'menu_history': [], 'week_signatures': [],
        })
        monkeypatch.setattr(db_mod, '_sb_client', fake, raising=False)
        monkeypatch.setattr(api_app, '_client_loader', None, raising=False)
        api_app.reset_caches()
        api_app.app.config['TESTING'] = True
        return api_app

    @pytest.mark.parametrize('path,body', [
        ('/api/v1/plan', {'client_name': CLIENT, 'start_date': MONDAY,
                          'num_days': 7, 'time_limit_seconds': TIME_LIMIT}),
        ('/api/v1/diagnose', {'client_name': CLIENT, 'start_date': MONDAY,
                              'num_days': 7}),
        ('/api/v1/pool-preview', {'source_pools': [], 'city': 'Pune'}),
    ])
    def test_pune_post_never_reads_bangalore(self, fleet_api, traced, path, body):
        r = _post(fleet_api, path, body)
        assert r.status_code == 200, r.get_json()
        assert 'bangalore.xlsx' not in traced, traced
        assert 'pune.xlsx' in traced, traced

    def test_pune_saved_plan_never_reads_bangalore(self, fleet_api, traced):
        r = _get(fleet_api,
                 f'/api/v1/saved-plan?client_name={CLIENT.replace(" ", "%20")}'
                 f'&start_date={MONDAY}&num_days=7')
        assert r.status_code == 200
        assert 'bangalore.xlsx' not in traced, traced

    def test_a_bangalore_request_never_reads_pune(self, fleet_api, traced):
        r = _post(fleet_api, '/api/v1/plan', {
            'client_name': 'Ather', 'start_date': MONDAY,
            'num_days': 5, 'time_limit_seconds': TIME_LIMIT})
        assert r.status_code == 200, r.get_json()
        assert 'pune.xlsx' not in traced, traced
        assert 'bangalore.xlsx' in traced, traced

    def test_editor_metadata_now_reads_no_workbook_at_all(self, fleet_api, traced):
        """This used to assert the opposite — that /editor-metadata legitimately
        loads EVERY city, because it reports which pool tokens belong to which.
        That was true and cost 4.8 s of cold start to produce about eight short
        strings.

        The answer is now precomputed into `city_items/pool_tokens.json`
        (scripts/build_pool_token_map.py), so the endpoint opens nothing. Kept as a
        cross-city test rather than deleted: reading zero workbooks is a strictly
        stronger statement of "no cross-city read" than reading both was.
        """
        r = _get(fleet_api, '/api/v1/editor-metadata')
        assert r.status_code == 200
        assert traced == [], (
            'expected no workbook reads — is pool_tokens.json missing? The '
            'endpoint falls back to parsing every workbook when it is, which is '
            'slow but not wrong: run scripts/build_pool_token_map.py')

    def test_it_still_reports_pool_tokens_for_both_cities(self, fleet_api):
        """The speed change must not have cost the information. Bangalore has real
        client pools; Pune's rows are all `common`, so an empty list is correct."""
        meta = _get(fleet_api, '/api/v1/editor-metadata').get_json()
        by_city = meta['client_pools_by_city']
        assert by_city['Bangalore'], by_city
        assert by_city['Pune'] == []

    def test_falling_back_to_the_workbooks_gives_the_same_answer(
            self, fleet_api, monkeypatch):
        """The map is a cache, so prove it agrees with the thing it caches."""
        with_map = _get(fleet_api, '/api/v1/editor-metadata').get_json()
        monkeypatch.setattr(fleet_api, '_pool_tokens_from_map', lambda _c: None)
        fleet_api.reset_caches()
        without = _get(fleet_api, '/api/v1/editor-metadata').get_json()
        assert with_map['client_pools_by_city'] == without['client_pools_by_city']


class TestItemPoolsAreCityScoped:
    """The editor must never offer another city's pool tokens."""

    def test_endpoint_scopes_by_city(self, pune_api):
        pune = _get(pune_api, '/api/v1/editor-metadata?city=Pune').get_json()
        blr = _get(pune_api, '/api/v1/editor-metadata?city=Bangalore').get_json()
        assert pune['available_client_pools'] == []
        assert blr['available_client_pools'], blr['available_client_pools']

    def test_editor_offers_nothing_for_pune_and_never_the_union(self, pune_api):
        """`pools_for_city` deliberately has no union fallback: offering a
        Bangalore pool to a Pune client is worse than offering none, because the
        API rejects it on save and it would match nothing in Pune's list anyway.
        """
        from customisation.main import pools_for_city
        metadata = _get(pune_api, '/api/v1/editor-metadata').get_json()
        assert metadata['available_client_pools'], "the union is still returned"
        assert pools_for_city(metadata, 'Pune') == []
        assert pools_for_city(metadata, 'Bangalore') == \
            metadata['client_pools_by_city']['Bangalore']

    def test_no_city_and_old_api_both_yield_nothing(self):
        from customisation.main import pools_for_city
        assert pools_for_city({'client_pools_by_city': {'Pune': []}}, None) == []
        # An API build predating client_pools_by_city: empty, not the union.
        assert pools_for_city({'available_client_pools': ['infineon']}, 'Pune') == []
