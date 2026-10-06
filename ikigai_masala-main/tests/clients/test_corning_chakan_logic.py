"""Corning Chakan (Pune): the client's stated guidelines, against a real week.

Three of these rules were wrong in a way no unit test would have shown, and
each failure mode is why this file solves a real menu rather than asserting on
config:

  * **a cap written where a floor was asked for.** "Sprouts gravy at least
    twice a week" was configured `max_per_week: 2`. A cap is satisfied by
    serving none, so the requirement read as enforced and was not;
  * **a floor written where a cap was asked for.** "Only two leafy-based
    dishes per week" carried `min: 2`, which forces two every week;
  * **a selector that matched almost nothing.** The 15-day biryani window
    selected `is_biryani_item`, which is set on 3 of the 15 biryanis in Pune's
    rice pool, and a backward-looking window cannot see the week it is
    planning. Both halves missing, a real week served a biryani on the
    Thursday and the Saturday while the rule reported zero.

The last one is the shape this repo keeps paying for: a rule that loads,
validates, and constrains nothing.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from src.ontology import repository

CLIENT = 'Corning Chakan'
BODY = {'client_name': CLIENT, 'start_date': '2026-11-02', 'num_days': 7,
        'time_limit_seconds': 40}


@pytest.fixture(scope='module')
def pune():
    df, _ = repository.menu_data('Pune')
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    return df


@pytest.fixture
def week(fake_supabase):
    """One real seven-day plan, solved once and read by every test below."""
    from api.app import app
    from tests.client_fixtures import CLIENTS
    fake_supabase.seed('clients', [dict(next(c for c in CLIENTS if c['name'] == CLIENT))])
    app.config['TESTING'] = True
    with app.test_client() as c:
        resp = c.post('/api/v1/plan', json=BODY)
    assert resp.status_code == 200, resp.get_json()
    solution = resp.get_json()['solution']
    return {iso: {s: v['item_base'] for s, v in day['items'].items()}
            for iso, day in solution.items()}


def _slot(week, slot):
    return {iso: str(row.get(slot) or '').lower() for iso, row in week.items()}


def _weekday(iso):
    return dt.date.fromisoformat(iso).strftime('%a').lower()


def test_sprouts_gravy_at_least_twice(week):
    """A FLOOR. Pune carries seven sprouts gravies, so two a week fits."""
    n = sum(1 for g in _slot(week, 'veg_gravy').values()
            if 'sprout' in g or 'matki' in g)
    assert n >= 2, f'sprouts gravy served {n} times, the client asked for two'


def test_sprouts_gravy_no_more_than_twice(week):
    n = sum(1 for g in _slot(week, 'veg_gravy').values()
            if 'sprout' in g or 'matki' in g)
    assert n <= 2


def test_at_most_two_leafy_veg_dry(week, pune):
    leafy = {str(i).lower() for i, v in zip(pune['item'], pune['is_leafy_based_dish'])
             if pd.to_numeric(v, errors='coerce') == 1}
    assert sum(1 for d in _slot(week, 'veg_dry').values() if d in leafy) <= 2


def test_at_most_one_biryani_in_the_week(week):
    """By NAME, not by the flag: `is_biryani_item` is set on 3 of the 15
    biryanis in Pune's rice pool, so a flag-only assertion here would pass
    while two biryanis sat in the menu."""
    n = sum(1 for r in _slot(week, 'rice').values() if 'biryani' in r or 'biriyani' in r)
    assert n <= 1, f'{n} biryanis in one week'


def test_soup_only_on_tuesday_thursday_saturday_sunday(week):
    for iso, soup in _slot(week, 'soup').items():
        if soup:
            assert _weekday(iso) in {'tue', 'thu', 'sat', 'sun'}, (iso, soup)


def test_sweets_only_on_monday_wednesday_friday(week):
    for iso, sweet in _slot(week, 'dessert').items():
        if sweet:
            assert _weekday(iso) in {'mon', 'wed', 'fri'}, (iso, sweet)


def test_every_day_carries_a_soup_or_a_sweet_but_not_both(week):
    """'Sweet and soup on alternate days' is not a rule of its own — it is
    what the two day-restrictions produce, and this is the assertion that
    says so."""
    soups, sweets = _slot(week, 'soup'), _slot(week, 'dessert')
    for iso in week:
        assert bool(soups[iso]) != bool(sweets[iso]), (iso, soups[iso], sweets[iso])


def test_no_liquid_sweets(week, pune):
    liquid = {str(i).lower() for i, v in zip(pune['item'], pune['is_liquid_dessert'])
              if pd.to_numeric(v, errors='coerce') == 1}
    assert not [d for d in _slot(week, 'dessert').values() if d in liquid]


def test_the_starter_is_a_chaat_and_only_on_thursday(week):
    """Live only because the counter now HAS a starter category; the rules
    were written while it did not and were inert until it was added."""
    for iso, starter in _slot(week, 'starter').items():
        if starter:
            assert _weekday(iso) == 'thu', (iso, starter)
            assert 'chaat' in starter or 'chat' in starter, starter


def test_paneer_gravy_exactly_once(week):
    n = sum(1 for g in _slot(week, 'veg_gravy').values() if 'paneer' in g)
    assert n == 1, f'paneer gravy served {n} times, the client asked for one'


def test_the_indian_bread_is_chapati_every_day(week):
    """'Indian Bread staple only Chapati' — a pin, so the same dish on all
    seven days. Asserted on the MENU rather than on the pin, because a pin
    that names no ontology dish is stamped as text and a pin for a slot the
    counter does not serve is dropped; both read as configured and neither
    reaches the plate."""
    breads = _slot(week, 'bread')
    assert set(breads.values()) == {'chapati'}, breads


def test_at_most_one_khichdi_in_the_week(week, pune):
    """The forward half of 'khichdi once in three weeks'. The backward half
    is a 21-day history window, which a single generated week cannot show."""
    fam = {str(i).lower() for i, s in zip(pune['item'], pune['sub_category'])
           if str(s).strip().lower() == 'north_khichdi'}
    n = sum(1 for r in _slot(week, 'rice').values() if r in fam)
    assert n <= 1, f'{n} khichdis in one week'


def test_the_khichdi_selector_is_not_inert(pune):
    """Note 9, and the biryani rule's own history: a selector that matches
    nothing loads, validates and constrains nothing while /plan answers 200.
    Seven dishes spelled khichdi, khichadi and khicha share one sub_category,
    which is why the rule reads the column and not the name."""
    fam = pune[pune['sub_category'].astype(str).str.strip().str.lower()
               == 'north_khichdi']
    assert len(fam) >= 5, f'only {len(fam)} north_khichdi rows left'
    assert set(fam['course_type'].astype(str).str.lower()) == {'rice'}, (
        'a khichdi moved out of the rice slot; the rule is scoped to rice')


def test_a_saved_khichdi_blocks_the_whole_family_for_three_weeks(monkeypatch, pune):
    """The backward half, which a single generated week cannot show.

    A 21-day window bans the family, not just the dish: `moong_khichadi` ten
    days after a `dal_khichdi` is still a khichdi inside the fortnight-and-a-
    half. The biryani rule's first version failed exactly here — it loaded,
    validated, and banned nothing — so this seeds history and reads the menu
    rather than asserting the rule exists.
    """
    from tests.fake_supabase import FakeSupabase
    from tests.client_fixtures import CLIENTS
    import src.db as db_mod
    import api.app as api_app

    served = dt.date.fromisoformat(BODY['start_date']) - dt.timedelta(days=10)
    fake = FakeSupabase(seed={
        'clients': [dict(next(c for c in CLIENTS if c['name'] == CLIENT))],
        'app_settings': [], 'week_signatures': [],
        'menu_history': [{'client_name': CLIENT, 'meal': 'lunch',
                          'service_date': served.isoformat(),
                          'menu': {'rice': 'dal_khichdi'}}],
    })
    monkeypatch.setattr(db_mod, '_sb_client', fake, raising=False)
    monkeypatch.setattr(api_app, '_client_loader', None, raising=False)
    api_app.reset_caches()
    api_app.app.config['TESTING'] = True
    from api.rate_limit import reset_for_tests
    reset_for_tests()

    resp = api_app.app.test_client().post('/api/v1/plan', json=BODY)
    body = resp.get_json() or {}
    assert resp.status_code == 200, body.get('error') or body.get('message')

    fam = {str(i).lower() for i, s in zip(pune['item'], pune['sub_category'])
           if str(s).strip().lower() == 'north_khichdi'}
    assert len(fam) > 1, 'one khichdi makes this test a no-repeat check'
    rices = {iso: str(d['items'].get('rice', {}).get('item_base') or '').lower()
             for iso, d in body['solution'].items()}
    hits = {iso: r for iso, r in rices.items() if r in fam}
    assert not hits, f'khichdi served inside 21 days of {served}: {hits}'


def test_one_saved_khichdi_bans_all_seven(pune):
    """The assertion above can pass by luck — the solver might not have
    wanted a khichdi that week. This is the one that cannot: the window bans
    the FAMILY from one member, which is the whole difference between a
    cadence and a no-repeat rule."""
    from src.history.history_manager import HistoryManager
    start = dt.date.fromisoformat(BODY['start_date'])
    fam = {str(i).lower() for i, s in zip(pune['item'], pune['sub_category'])
           if str(s).strip().lower() == 'north_khichdi'}
    hm = HistoryManager()
    hm.load_from_dataframes(HistoryManager.explode_history_rows(
        [{'client_name': CLIENT, 'service_date': (start - dt.timedelta(days=10)).isoformat(),
          'menu': {'rice': 'dal_khichdi'}}]))
    dates = [start + dt.timedelta(days=i) for i in range(7)]
    banned = hm.selector_banned_by_date(dates, fam, 21)
    assert all(banned[d] == fam for d in dates), banned
    # ...and lets go on the far side of the window.
    beyond = [start + dt.timedelta(days=i) for i in range(12, 15)]
    assert all(not hm.selector_banned_by_date(beyond, fam, 21)[d] for d in beyond)
