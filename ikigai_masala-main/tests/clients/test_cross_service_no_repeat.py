"""A dish served at dinner does not come back at lunch for three weeks.

The client's words: "items that came in lunch can't come in dinner for at
least 3 weeks, or vice versa."

Why this file exists rather than a line in a design note. The guarantee is
real but it is an EMERGENT one — nothing is named after it, and no single
place says "services share a cooldown". It falls out of three unrelated
facts, any one of which could be changed by someone who has never heard of
the requirement:

  1. ``_build_history_context`` queries ``menu_history`` with a client filter
     and a date filter and **no meal filter**;
  2. ``explode_history_rows`` throws the ``meal`` column away when it flattens
     those rows into the ``(client, date, slot, item)`` shape the cooldown
     reads, so the reader could not tell lunch from dinner even if it wanted
     to;
  3. ``/save`` writes BOTH services (note 39), so dinner is in the history to
     begin with.

Add ``.eq('meal', meal)`` to (1) as an "obvious" optimisation and the whole
requirement disappears with no test failing and no log line — lunch would
simply stop seeing dinner, and the menus would still look fine.

Within ONE generation the mechanism is different and already note 39's: the
planner hands lunch's dishes to dinner as ``exclude_items`` and the server
bans them on every DAY of the horizon, which is the "strictly no repetition
in the same week" half.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib

import pytest

from src.constants import DEFAULT_ITEM_COOLDOWN_DAYS
from src.history.history_manager import HistoryManager

CITY_RULES = (pathlib.Path(__file__).resolve().parents[2]
              / 'data' / 'configs' / 'city_rules')
PLAN_DAY = dt.date(2026, 11, 2)


def _history(*rows):
    """A HistoryManager loaded the way the app loads one, meals and all."""
    hm = HistoryManager()
    hm.load_from_dataframes(HistoryManager.explode_history_rows(list(rows)))
    return hm


def _row(days_ago, meal, **menu):
    return {'client_name': 'Corning Chakan', 'meal': meal,
            'service_date': (PLAN_DAY - dt.timedelta(days=days_ago)).isoformat(),
            'menu': menu}


class TestTheWindowCannotTellLunchFromDinner:
    def test_the_meal_is_dropped_on_the_way_in(self):
        """Fact 2, asserted directly: this is the line that makes the
        guarantee true, and it is one word long."""
        long_df = HistoryManager.explode_history_rows(
            [_row(5, 'dinner', veg_gravy='paneer_butter_masala')])
        assert 'meal' not in long_df.columns
        assert list(long_df['item_base']) == ['paneer_butter_masala']

    def test_last_weeks_dinner_is_banned_from_this_weeks_lunch(self):
        banned = _history(
            _row(5, 'dinner', veg_gravy='paneer_butter_masala'),
        ).banned_items_by_date([PLAN_DAY])
        assert 'paneer_butter_masala' in banned[PLAN_DAY]

    def test_and_the_other_way_round(self):
        """Same assertion with the services swapped. It passes for the same
        reason, which is the point — there is one window, not two."""
        banned = _history(
            _row(5, 'lunch', veg_gravy='paneer_butter_masala'),
        ).banned_items_by_date([PLAN_DAY])
        assert 'paneer_butter_masala' in banned[PLAN_DAY]

    def test_the_window_is_three_weeks_and_has_an_edge(self):
        """A ban with no edge is not a window. 20 days back is still banned,
        22 is free — so the rule is a cadence rather than a deletion."""
        hm = _history(
            _row(20, 'dinner', veg_gravy='inside_the_window'),
            _row(22, 'dinner', veg_gravy='outside_the_window'),
        )
        banned = hm.banned_items_by_date([PLAN_DAY])[PLAN_DAY]
        assert 'inside_the_window' in banned
        assert 'outside_the_window' not in banned

    def test_a_staple_is_still_exempt(self):
        """Three weeks applies to variety dishes. Steamed rice, the plain
        curd and a declared chapati recur by design and must not be caught."""
        banned = _history(
            _row(5, 'dinner', white_rice='steamed rice'),
        ).banned_items_by_date([PLAN_DAY], const_slots=['white_rice'])
        assert banned[PLAN_DAY] == set()


class TestEveryCopyOfTheNumberAgrees:
    """Three places needed this window and each used to carry its own 20.

    A reader who changes one and not the others gets a system where the rule
    bans for three weeks, the database query looks back two and a half, and a
    fresh client's column says something else again — all without an error.
    """

    def test_the_default_is_three_weeks(self):
        assert DEFAULT_ITEM_COOLDOWN_DAYS == 21

    def test_the_rule_the_history_reader_and_the_column_share_it(self):
        import inspect
        from src.client.client_config import (
            DEFAULT_ITEM_COOLDOWN_DAYS as column_default)
        from src.menu_rules.cooldown_rules import ItemCooldownMenuRule
        rule = ItemCooldownMenuRule({'name': 'c', 'type': 'item_cooldown'})
        reader = inspect.signature(
            HistoryManager.banned_items_by_date).parameters['cooldown_days']
        assert rule.cooldown_days == DEFAULT_ITEM_COOLDOWN_DAYS
        assert reader.default == DEFAULT_ITEM_COOLDOWN_DAYS
        assert column_default == DEFAULT_ITEM_COOLDOWN_DAYS

    @pytest.mark.parametrize('city', ['bangalore', 'chennai', 'pune'])
    def test_every_city_that_ships_its_own_cooldown_says_three_weeks(self, city):
        """Hyderabad and NCR extend Bangalore and ship none of their own."""
        rules = json.loads((CITY_RULES / f'{city}.json').read_text())['rules']
        cds = [r for r in rules if r.get('type') == 'item_cooldown']
        assert len(cds) == 1, f'{city} ships {len(cds)} item_cooldown rules'
        assert cds[0]['cooldown_days'] == 21
        assert cds[0]['name'] == 'item_cooldown_21d', (
            'the name carries the number; a rule called _20d holding 21 is the '
            'drift this repo keeps paying for')


def test_the_history_query_has_no_meal_filter():
    """Fact 1, asserted lexically because there is nothing else to assert on:
    the filter's ABSENCE is the feature, and absence has no runtime signal.

    A substring check is blunt, and it is the only net that catches the one
    edit that would silently delete this guarantee.
    """
    src = (pathlib.Path(__file__).resolve().parents[2]
           / 'src' / 'application' / 'history.py').read_text()
    body = src.split("sb.table('menu_history')", 1)[1].split('.execute()', 1)[0]
    assert 'meal' not in body, (
        "menu_history is queried with a meal filter — lunch can no longer see "
        "dinner's dishes, and the cross-service no-repeat is gone")


@pytest.mark.parametrize('meal_in_history', ['dinner'])
def test_a_real_lunch_plan_will_not_reprint_last_weeks_dinner(
        monkeypatch, meal_in_history):
    """The three facts above, wired together through /plan.

    Seeds ONE dinner dish five days before the week and checks the lunch menu
    never serves it. A unit test of the reader cannot catch a caller that
    forgets to pass the history through.
    """
    from tests.fake_supabase import FakeSupabase
    from tests.client_fixtures import CLIENTS
    import src.db as db_mod
    import api.app as api_app

    client = dict(next(c for c in CLIENTS if c['name'] == 'Corning Chakan'))
    seeded = 'paneer_butter_masala'
    fake = FakeSupabase(seed={
        'clients': [client], 'app_settings': [], 'week_signatures': [],
        'menu_history': [_row(5, meal_in_history, veg_gravy=seeded)],
    })
    monkeypatch.setattr(db_mod, '_sb_client', fake, raising=False)
    monkeypatch.setattr(api_app, '_client_loader', None, raising=False)
    api_app.reset_caches()
    api_app.app.config['TESTING'] = True

    from api.rate_limit import reset_for_tests
    reset_for_tests()
    resp = api_app.app.test_client().post('/api/v1/plan', json={
        'client_name': 'Corning Chakan', 'start_date': PLAN_DAY.isoformat(),
        'num_days': 7, 'time_limit_seconds': 40, 'meal': 'lunch'})
    body = resp.get_json() or {}
    assert resp.status_code == 200, body.get('error') or body.get('message')

    # Guard against a vacuous pass: the dish has to be one this counter could
    # have served, or "it did not appear" says nothing at all.
    from src.ontology import repository
    pune, _ = repository.menu_data('Pune')
    assert seeded in set(pune['item'].astype(str)), (
        f'{seeded} is not in the Pune list any more — pick another veg gravy '
        f'or this test proves nothing')

    served = {v['item_base'] for day in body['solution'].values()
              for v in day['items'].values()}
    assert seeded not in served, (
        f'{seeded} was served at dinner five days ago and is back at lunch')


if __name__ == '__main__':      # a runnable check without pytest
    raise SystemExit(pytest.main([__file__, '-q']))
