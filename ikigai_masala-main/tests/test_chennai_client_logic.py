"""Toast Tab CHN against its own sample week.

The source is a 7-day SERVICE HISTORY (Wed 01 Jul – Thu 09 Jul 2026, weekdays
only), not a written rulebook, so every rule here was read off the grid. The
structural findings the sample settles 7/7 are:

  * exactly ONE rice per day — white rice on the four south days, a flavoured
    rice on the north and biryani days, never both;
  * rasam + curd on the white-rice days, curd rice on the flavoured-rice days
    (with no plain rice to eat rasam with, the sour component moves);
  * non-veg, bread, dessert and appalam every single day;
  * the bread is always a wheat flatbread — chapati, paratha, kulcha or kothu
    parotta — and never the dosai/idly family.

The one thing the sample does NOT settle is the weekday→theme map: it spans two
part-weeks that disagree (Wed is south on 01 Jul but biryani on 08 Jul; Thu is
north on 02 Jul but south on 09 Jul). The map used here is inferred from the
later, more complete run — Mon/Thu/Fri south, Tue north, Wed biryani — which fits
5 of the 7 observed days. The weekday lists in `client_rules.json` FOLLOW from
it; what the sample actually determines is the THEME each slot belongs to.
"""

from __future__ import annotations

import datetime as dt

import pytest

from tests.fake_supabase import FakeSupabase

MONDAY = '2026-08-03'
TIME_LIMIT = 90
MON, TUE, WED, THU, FRI = 0, 1, 2, 3, 4
SOUTH_DAYS = {MON, THU, FRI}
FLAVOURED_DAYS = {TUE, WED}

COUNTER = {
    'name': 'Lunch',
    'categories': ['salad', 'bread', 'veg_gravy', 'veg_dry', 'sambar', 'rasam',
                   'curd_side', 'white_rice', 'rice', 'curd_rice',
                   'nonveg_main', 'dessert', 'papad'],
    'slot_counts': {'salad': 1, 'bread': 1, 'veg_gravy': 2, 'veg_dry': 1,
                    'sambar': 1, 'rasam': 1, 'curd_side': 1, 'rice': 1,
                    'curd_rice': 1, 'nonveg_main': 1, 'dessert': 1},
    'theme_map': {'monday': 'south', 'tuesday': 'north', 'wednesday': 'biryani',
                  'thursday': 'south', 'friday': 'south'},
}
ROW = {
    'name': 'ToastTab CHN', 'city': 'Chennai', 'serve_weekends': False,
    'working_days': None, 'item_cooldown_days': None, 'source_pools': [],
    'version': 1, 'counters': [COUNTER],
}


@pytest.fixture(scope='module')
def plan():
    """One five-day solve, shared by every assertion below."""
    import api.app as api_app
    import src.db as db_mod
    from api.rate_limit import reset_for_tests

    fake = FakeSupabase(seed={
        'clients': [dict(ROW)], 'app_settings': [],
        'menu_history': [], 'week_signatures': [],
    })
    old = getattr(db_mod, '_sb_client', None)
    db_mod._sb_client = fake
    api_app._client_loader = None
    api_app.reset_caches()
    api_app.app.config['TESTING'] = True
    try:
        reset_for_tests()
        resp = api_app.app.test_client().post('/api/v1/plan', json={
            'client_name': 'ToastTab CHN', 'start_date': MONDAY,
            'num_days': 5, 'time_limit_seconds': TIME_LIMIT,
        })
        body = resp.get_json() or {}
        assert resp.status_code == 200, body.get('error') or body.get('message')
        yield body
    finally:
        db_mod._sb_client = old
        api_app._client_loader = None


@pytest.fixture(scope='module')
def chennai_df():
    from api.config import city_excel_path
    from src.preprocessor.data_cleanser import DataCleanser
    from src.preprocessor.excel_reader import ExcelReader
    return DataCleanser(ExcelReader(city_excel_path('Chennai')).read()).clean()


def _by_weekday(plan, slot):
    """``{weekday_index: item_base}`` for one slot; absent days are omitted."""
    out = {}
    for key, day in plan['solution'].items():
        entry = (day['items'] or {}).get(slot)
        if entry and entry.get('item_base'):
            out[dt.date.fromisoformat(key).weekday()] = entry['item_base']
    return out


class TestTheDailySpine:
    def test_five_weekdays(self, plan):
        """`serve_weekends` is false — the sample skipped Sat 04 and Sun 05."""
        assert len(plan['solution']) == 5

    @pytest.mark.parametrize('slot', ['bread', 'nonveg_main', 'dessert',
                                      'sambar', 'veg_dry', 'salad'])
    def test_slot_runs_every_day(self, plan, slot):
        assert set(_by_weekday(plan, slot)) == {MON, TUE, WED, THU, FRI}, slot

    def test_two_veg_gravies_every_day(self, plan):
        for n in ('veg_gravy__1', 'veg_gravy__2'):
            assert set(_by_weekday(plan, n)) == {MON, TUE, WED, THU, FRI}, n

    def test_nonveg_every_day(self, plan, chennai_df):
        """'EGG KURMA / CHICKEN MASALA / FISH KUZHAMBU' — one non-veg daily."""
        nv = _by_weekday(plan, 'nonveg_main')
        assert len(nv) == 5
        pool = set(chennai_df[chennai_df['course_type'] == 'nonveg_main']['item'])
        assert set(nv.values()) <= pool


class TestExactlyOneRicePerDay:
    """The sample is 7/7: white rice on south days, a flavoured rice on the
    north and biryani days, never both and never neither."""

    def test_white_rice_only_on_south_days(self, plan):
        assert set(_by_weekday(plan, 'white_rice')) == SOUTH_DAYS

    def test_flavoured_rice_only_on_north_and_biryani_days(self, plan):
        assert set(_by_weekday(plan, 'rice')) == FLAVOURED_DAYS

    def test_never_two_rices_on_one_day(self, plan):
        flavoured = _by_weekday(plan, 'rice')
        white = _by_weekday(plan, 'white_rice')
        both = sorted(set(flavoured) & set(white))
        assert not both, f'weekday(s) {both} serve two rices'

    def test_every_day_has_exactly_one_rice(self, plan):
        flavoured = _by_weekday(plan, 'rice')
        white = _by_weekday(plan, 'white_rice')
        for wd in range(5):
            assert (wd in flavoured) ^ (wd in white), f'weekday {wd}'


class TestTheSourComponentFollowsTheRice:
    """'RASAM / CURD' on the white-rice days, 'CURD RICE' on the others."""

    def test_rasam_only_on_south_days(self, plan):
        assert set(_by_weekday(plan, 'rasam')) == SOUTH_DAYS

    def test_curd_rice_only_on_flavoured_rice_days(self, plan):
        assert set(_by_weekday(plan, 'curd_rice')) == FLAVOURED_DAYS

    def test_rasam_and_curd_rice_never_share_a_day(self, plan):
        assert not (set(_by_weekday(plan, 'rasam'))
                    & set(_by_weekday(plan, 'curd_rice')))

    def test_the_biryani_day_gets_a_raita_not_a_rasam(self, plan):
        """Sample Wed 08: RAITHA beside the veg biryani, no rasam."""
        assert WED in _by_weekday(plan, 'curd_side')
        assert WED not in _by_weekday(plan, 'rasam')


class TestBreadIsAlwaysAWheatFlatbread:
    """Every one of the seven sampled breads is chapati, paratha, kulcha or
    kothu parotta. Chennai's pool also holds 9 rice-breads (dosai, idly, appam)
    and the solver served 'podi idly' as the bread row until this was pinned."""

    def test_no_dosai_or_idly_all_week(self, plan, chennai_df):
        import pandas as pd
        breads = _by_weekday(plan, 'bread')
        assert len(breads) == 5
        by_item = chennai_df.set_index('item')
        for wd, item in breads.items():
            row = by_item.loc[item]
            rice_bread = int(pd.to_numeric(
                [row.get('is_rice_bread')], errors='coerce')[0] or 0)
            assert rice_bread == 0, f'weekday {wd}: {item} is a rice bread'

    def test_every_bread_is_in_the_wheat_family(self, plan, chennai_df):
        import pandas as pd
        flags = ['is_plain_phulka_chapathi', 'is_paratha', 'is_maida_bread',
                 'is_tandoori_roti']
        by_item = chennai_df.set_index('item')
        for wd, item in _by_weekday(plan, 'bread').items():
            row = by_item.loc[item]
            on = [f for f in flags
                  if int(pd.to_numeric([row.get(f)], errors='coerce')[0] or 0) == 1]
            assert on, f'weekday {wd}: {item} matches no wheat-flatbread flag'


class TestEveryDishIsAChennaiDish:
    def test_no_dish_comes_from_another_city(self, plan, chennai_df):
        """123 of Chennai's items also exist in Bangalore, so a spot check would
        not catch a plan built off the wrong ontology."""
        names = set(chennai_df['item'])
        stamped = {'steamed rice', 'Papad'}
        for key, day in plan['solution'].items():
            for slot, entry in (day['items'] or {}).items():
                item = entry.get('item_base')
                if not item or item in stamped:
                    continue
                assert item in names, f'{key} {slot}: {item} is not a Chennai dish'


class TestNoDiagnosticNoise:
    def test_diagnose_is_clean(self):
        """No errors AND no warnings. The pre-flight gate caught two real
        conflicts while this client was being built — the maida-bread cap and
        the bread cuisine lock — so a clean report is meaningful here."""
        import api.app as api_app
        import src.db as db_mod
        from api.rate_limit import reset_for_tests

        fake = FakeSupabase(seed={
            'clients': [dict(ROW)], 'app_settings': [],
            'menu_history': [], 'week_signatures': [],
        })
        old = getattr(db_mod, '_sb_client', None)
        db_mod._sb_client = fake
        api_app._client_loader = None
        api_app.reset_caches()
        try:
            reset_for_tests()
            body = api_app.app.test_client().post('/api/v1/diagnose', json={
                'client_name': 'ToastTab CHN', 'start_date': MONDAY,
                'num_days': 5,
            }).get_json()
            noisy = [d for d in body['rule_diagnostics']
                     if d['severity'] in ('error', 'warning')]
            assert not noisy, noisy
        finally:
            db_mod._sb_client = old
            api_app._client_loader = None
