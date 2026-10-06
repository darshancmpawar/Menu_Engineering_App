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
