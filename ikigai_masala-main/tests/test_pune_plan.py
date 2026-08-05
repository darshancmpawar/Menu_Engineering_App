"""End-to-end: the Pune CITY ruleset, on a counter with no client overrides.

The unit tests next door prove the ruleset loads and the rule types work. This
one proves the wiring: `clients.city = 'Pune'` must reach both the ontology and
the ruleset, and the menu that comes back must obey the rules that bite. It runs
a real solve — a 5-day, 8-slot Pune counter takes well under a second, so it
stays in the fast suite where a regression fails on the pull request.

Per-client rules are tested in `test_pune_client_logic.py`; this file deliberately
uses a name with no `client_rules.json` entry so the two do not mask each other.
"""

import datetime as dt

import pandas as pd
import pytest

from tests.fake_supabase import FakeSupabase

MONDAY = '2026-08-03'   # Monday, ISO week 32
TIME_LIMIT = 30

# Deliberately NOT a real client name: this file tests the CITY ruleset, so the
# counter must carry no `client_rules.json` overrides. Amadeus Pune has a full set
# of them (rice on two weekdays only, four slots off on Sunday), which would mask
# what the city rules do on their own — and did: the rice-cuisine assertion below
# started passing on two rice days instead of seven.
REFERENCE_PUNE = {
    'name': 'Pune Reference Counter',
    'version': 1,
    'city': 'Pune',
    'serve_weekends': True,
    'item_cooldown_days': 20,
    'source_pools': [],
    'counters': [{
        'name': 'Counter 1',
        'theme_map': {d: 'north' for d in (
            'monday', 'tuesday', 'wednesday', 'thursday', 'friday')},
        'categories': ['welcome_drink', 'salad', 'bread', 'rice', 'veg_dry',
                       'veg_gravy', 'dal', 'dessert', 'white_rice', 'papad'],
        'slot_counts': {'welcome_drink': 1, 'salad': 1, 'bread': 1, 'rice': 1,
                        'veg_dry': 1, 'veg_gravy': 1, 'dal': 1, 'dessert': 1},
    }],
}


@pytest.fixture
def pune_client(monkeypatch):
    import src.db as db_mod
    fake = FakeSupabase(seed={
        'clients': [dict(REFERENCE_PUNE)],
        'app_settings': [],
        'menu_history': [],
        'week_signatures': [],
    })
    monkeypatch.setattr(db_mod, '_sb_client', fake, raising=False)
    import api.app as api_app
    monkeypatch.setattr(api_app, '_client_loader', None, raising=False)
    api_app.reset_caches()
    api_app.app.config['TESTING'] = True
    return api_app


def _plan(api_app, start=MONDAY, days=5):
    from api.rate_limit import reset_for_tests
    reset_for_tests()
    resp = api_app.app.test_client().post('/api/v1/plan', json={
        'client_name': 'Pune Reference Counter',
        'start_date': start,
        'num_days': days,
        'time_limit_seconds': TIME_LIMIT,
    })
    return resp, (resp.get_json() or {})


def _by_slot(body, slot):
    """[(date, item_base)] for one slot, in date order."""
    out = []
    for key in sorted(body['solution']):
        entry = body['solution'][key]['items'].get(slot)
        if entry:
            out.append((key, entry['item_base']))
    return out


@pytest.fixture(scope='module')
def pune_df():
    from api.config import city_excel_path
    from src.preprocessor.data_cleanser import DataCleanser
    from src.preprocessor.excel_reader import ExcelReader
    return DataCleanser(ExcelReader(city_excel_path('Pune')).read()).clean()


def _attr(pune_df, item, col):
    row = pune_df[pune_df['item'] == item]
    return None if row.empty else row.iloc[0][col]


def _is(pune_df, item, flag):
    value = _attr(pune_df, item, flag)
    return bool(pd.to_numeric(pd.Series([value]), errors='coerce').fillna(0).iloc[0])


class TestPuneEndToEnd:
    def test_plan_succeeds(self, pune_client):
        resp, body = _plan(pune_client)
        assert resp.status_code == 200, body.get('error') or body.get('message')
        assert len(body['solution']) == 5

    def test_diagnose_reports_no_errors(self, pune_client):
        from api.rate_limit import reset_for_tests
        reset_for_tests()
        resp = pune_client.app.test_client().post('/api/v1/diagnose', json={
            'client_name': 'Pune Reference Counter', 'start_date': MONDAY, 'num_days': 5,
        })
        body = resp.get_json()
        assert resp.status_code == 200
        assert body['summary']['would_succeed'] is True, [
            d for d in body['rule_diagnostics'] if d['severity'] == 'error'
        ]

    def test_every_dish_comes_from_the_pune_list(self, pune_client, pune_df):
        """The bug this guards: a Pune client planning off Bangalore's ontology.
        123 of Pune's 272 items also exist in Bangalore, so checking a couple of
        dishes would not catch it — every dish must be in the Pune list."""
        _resp, body = _plan(pune_client)
        pune_items = set(pune_df['item'])
        constants = {'steamed rice', 'Papad', 'Pickle', 'chutney'}
        for key, day in body['solution'].items():
            for slot, entry in day['items'].items():
                name = entry['item_base']
                if name in constants:
                    continue
                assert name in pune_items, f"{key}/{slot}={name} is not a Pune item"

    def test_no_dish_renders_as_nonveg(self, pune_client):
        """The Pune list is entirely vegetarian, so nothing may be tagged red."""
        _resp, body = _plan(pune_client)
        for day in body['solution'].values():
            for slot, entry in day['items'].items():
                assert not entry.get('is_nonveg'), (slot, entry['item_base'])

    def test_weekends_are_covered(self, pune_client):
        """This counter has serve_weekends set — a 7-day ask must include Sat/Sun
        rather than silently skipping to the next week."""
        resp, body = _plan(pune_client, days=7)
        assert resp.status_code == 200, body.get('error')
        days = {dt.date.fromisoformat(k).weekday() for k in body['solution']}
        assert {5, 6} <= days


class TestPuneMenuObeysTheRulebook:
    @pytest.fixture(scope='class')
    def plan(self, request):
        # One solve shared by the assertions below; each checks a different rule.
        import src.db as db_mod
        import api.app as api_app
        fake = FakeSupabase(seed={
            'clients': [dict(REFERENCE_PUNE)], 'app_settings': [],
            'menu_history': [], 'week_signatures': [],
        })
        old_sb = getattr(db_mod, '_sb_client', None)
        db_mod._sb_client = fake
        api_app._client_loader = None
        api_app.reset_caches()
        api_app.app.config['TESTING'] = True
        try:
            resp, body = _plan(api_app)
            assert resp.status_code == 200, body.get('error') or body.get('message')
            yield body
        finally:
            db_mod._sb_client = old_sb
            api_app._client_loader = None

    def test_r33_dal_colour_never_repeats_on_consecutive_days(self, plan, pune_df):
        colours = [_attr(pune_df, item, 'item_color')
                   for _d, item in _by_slot(plan, 'dal')]
        assert all(a != b for a, b in zip(colours, colours[1:])), colours

    def test_r28_dessert_form_never_repeats_on_consecutive_days(self, plan, pune_df):
        forms = [_attr(pune_df, item, 'dessert_form')
                 for _d, item in _by_slot(plan, 'dessert')]
        assert all(a != b for a, b in zip(forms, forms[1:])), forms

    def test_r25_at_least_two_yellow_dal_days(self, plan, pune_df):
        yellow = [item for _d, item in _by_slot(plan, 'dal')
                  if _is(pune_df, item, 'is_yellow_dal')]
        assert len(yellow) >= 2, yellow

    def test_r19_at_most_one_mixed_veg_pulao_or_biryani(self, plan, pune_df):
        hits = [item for _d, item in _by_slot(plan, 'rice')
                if _is(pune_df, item, 'is_mixedveg_pulao')
                or _is(pune_df, item, 'is_mixedveg_biryani')]
        assert len(hits) <= 1, hits

    def test_r12_at_most_two_aloo_gravies(self, plan, pune_df):
        hits = [item for _d, item in _by_slot(plan, 'veg_gravy')
                if _is(pune_df, item, 'is_aloo_gravy')]
        assert len(hits) <= 2, hits

    @pytest.mark.parametrize('flag', [
        'is_premium_gravy', 'is_mixedveg_gravy', 'is_kurma_gravy',
        'is_veg_kofta_gravy', 'is_kabuli_chana_gravy', 'is_kadhi_dal',
    ])
    def test_weekly_gravy_caps(self, plan, pune_df, flag):
        hits = [item for _d, item in _by_slot(plan, 'veg_gravy')
                if _is(pune_df, item, flag)]
        assert len(hits) <= 1, (flag, hits)

    def test_r13_at_most_one_premium_veg_item_per_day(self, plan, pune_df):
        for key, day in plan['solution'].items():
            premium = [e['item_base'] for e in day['items'].values()
                       if _is(pune_df, e['item_base'], 'is_premium_veg')]
            assert len(premium) <= 1, (key, premium)

    def test_r43_at_most_one_leafy_dish_per_day(self, plan, pune_df):
        for key, day in plan['solution'].items():
            leafy = [e['item_base'] for e in day['items'].values()
                     if _is(pune_df, e['item_base'], 'is_leafy_based_dish')]
            assert len(leafy) <= 1, (key, leafy)

    def test_r1_r2_three_colours_and_no_more_than_two_alike(self, plan, pune_df):
        colour_slots = {'rice', 'veg_gravy', 'veg_dry', 'dal', 'dessert'}
        for key, day in plan['solution'].items():
            colours = [
                _attr(pune_df, e['item_base'], 'item_color')
                for slot, e in day['items'].items() if slot in colour_slots
            ]
            counts = pd.Series(colours).value_counts()
            assert len(counts) >= 3, (key, colours)
            assert counts.max() <= 2, (key, colours)

    def test_r3_rice_and_gravy_differ_in_colour(self, plan, pune_df):
        for key, day in plan['solution'].items():
            rice = day['items'].get('rice')
            gravy = day['items'].get('veg_gravy')
            if not rice or not gravy:
                continue
            assert (_attr(pune_df, rice['item_base'], 'item_color')
                    != _attr(pune_df, gravy['item_base'], 'item_color')), key

    def test_r51_white_rice_every_day(self, plan):
        for key, day in plan['solution'].items():
            assert day['items'].get('white_rice'), key

    def test_no_off_theme_chinese_or_continental_main(self, plan, pune_df):
        """The theme filter's cuisine exclusivity: a north-themed counter must
        not serve veg_fried_rice or burnt_garlic_rice as its rice."""
        for slot in ('rice', 'veg_gravy', 'veg_dry'):
            for key, item in _by_slot(plan, slot):
                assert _attr(pune_df, item, 'cuisine_family') not in (
                    'chinese', 'continental'), (key, slot, item)

    def test_regional_rice_stays_eligible(self, plan, pune_df):
        """`rice` is exempt from cuisine narrowing so Pune's Maharashtrian and
        south rice baths can appear on a north-themed counter. If the exemption
        were dropped, every rice would be cuisine_family=north_indian."""
        families = {_attr(pune_df, item, 'cuisine_family')
                    for _d, item in _by_slot(plan, 'rice')}
        assert len(families) > 1, families


class TestPuneSecondWeek:
    """R36's real payoff: the week after the first one is saved.

    Pune's bread slot has exactly two dishes. Under the 20-day item cooldown both
    are banned once week one is in history, which empties the slot — unless the
    staple declaration exempts them, which is what R36 says to do.
    """

    def test_bread_survives_a_week_of_history(self, monkeypatch):
        import src.db as db_mod
        history = [
            {
                'client_name': 'Pune Reference Counter',
                'service_date': d,
                'menu': {'bread': bread, 'dal': dal},
            }
            for d, bread, dal in [
                ('2026-07-27', 'chapati', 'dal_fry'),
                ('2026-07-28', 'phulka', 'dal_palak'),
                ('2026-07-29', 'chapati', 'dal_makhani'),
                ('2026-07-30', 'phulka', 'dal_adraki'),
                ('2026-07-31', 'chapati', 'dal_tadka'),
            ]
        ]
        fake = FakeSupabase(seed={
            'clients': [dict(REFERENCE_PUNE)], 'app_settings': [],
            'menu_history': history, 'week_signatures': [],
        })
        monkeypatch.setattr(db_mod, '_sb_client', fake, raising=False)
        import api.app as api_app
        monkeypatch.setattr(api_app, '_client_loader', None, raising=False)
        api_app.reset_caches()
        api_app.app.config['TESTING'] = True

        resp, body = _plan(api_app)
        assert resp.status_code == 200, body.get('error') or body.get('message')
        breads = [item for _d, item in _by_slot(body, 'bread')]
        assert len(breads) == 5
        assert set(breads) <= {'chapati', 'phulka'}
        # The dals used last week must NOT come back — the exemption is scoped to
        # the declared staples, it does not switch the cooldown off wholesale.
        used = {'dal_fry', 'dal_palak', 'dal_makhani', 'dal_adraki', 'dal_tadka'}
        assert not (set(item for _d, item in _by_slot(body, 'dal')) & used)
