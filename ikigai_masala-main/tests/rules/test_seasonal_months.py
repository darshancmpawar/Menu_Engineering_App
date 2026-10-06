"""Mango is a March-to-June dish, and `allowed_months` is how a rule says so.

A season is a property of the DATE. `allowed_day_types` scopes by cuisine and
`forbidden_weekdays` by service day, and neither can express "only in mango
season", so this is a third ban axis on the same rule.

It is deliberately NOT part of the seasonal high-risk lists: those are
generated per plan from the owner's sheet by a script and must not be
hand-edited, and this is a standing menu policy rather than a produce-safety
list.

**Why the assertions below are on the CONSTRAINT and not on a generated
menu.** A week solved in November serves no mango — and so does a week solved
in May, because out of eighty-two mango dishes in Bangalore the objective
happens to want none of them. "No mango in November" measured off a menu
therefore passes whether the rule exists or not, which is the shape of test
this repo has been bitten by twice (the biryani flag, the khichdi family). The
integration test at the bottom asserts the thing a solve CAN tell you: that
taking the dishes away does not starve anybody.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import pathlib

import pandas as pd
import pytest
from ortools.sat.python import cp_model

from src.menu_rules.relaxations import RELAXATION
from src.menu_rules.selector_frequency_rule import SelectorFrequencyRule

CITY_RULES = (pathlib.Path(__file__).resolve().parents[2]
              / 'data' / 'configs' / 'city_rules')
RULE_NAME = 'mango_is_a_march_to_june_dish'
OWNERS = [('bangalore', 'Bangalore'), ('chennai', 'Chennai'), ('pune', 'Pune')]


def _config(city='bangalore'):
    rules = json.loads((CITY_RULES / f'{city}.json').read_text())['rules']
    return next(r for r in rules if r.get('name') == RULE_NAME)


class _Cell:
    def __init__(self, model, base_slot, rows):
        self.base_slot = base_slot
        self.d_idx = 0
        self.x_vars = [model.NewBoolVar(str(r['item'])) for r in rows]
        self.cand_rows = [pd.Series(r) for r in rows]
        model.AddExactlyOne(self.x_vars)


def _dish(item, ki=''):
    return {'item': item, 'key_ingredient': ki, 'course_type': 'dessert'}


def _apply(month, rows, *, rule=None, day_idx=0):
    """Apply the shipped rule to one day in *month*; return (model, cell)."""
    model = cp_model.CpModel()
    cell = _Cell(model, 'dessert', rows)
    cell.d_idx = day_idx
    r = SelectorFrequencyRule(rule or _config())
    r.apply(model, {}, None, {
        'cells': [cell], 'dates': [dt.date(2026, month, 10)],
        'day_types': ['mix'],
        'link_any_fn': lambda *a, **k: None,
    })
    return model, cell


def _forced_off(model, cell, item):
    """Is *item* unservable under *model*?

    Asked by DEMANDING the dish and seeing whether the model still solves: a
    real ban makes that infeasible. Reading the solution instead would prove
    nothing — with the ban lifted the solver is free to pick either dish, so
    "it did not choose the mango" is not "it could not".

    Mutates *model*, which is why every test builds its own.
    """
    idx = [str(r['item']) for r in cell.cand_rows].index(item)
    model.Add(cell.x_vars[idx] == 1)
    return cp_model.CpSolver().Solve(model) == cp_model.INFEASIBLE


ROWS = [_dish('mango_burfi', 'mango'), _dish('gulab_jamun', 'milk')]


class TestTheSeasonIsEnforced:
    @pytest.mark.parametrize('month', [3, 4, 5, 6])
    def test_in_season_the_dish_is_free(self, month):
        model, cell = _apply(month, ROWS)
        assert not _forced_off(model, cell, 'mango_burfi')

    @pytest.mark.parametrize('month', [1, 2, 7, 8, 9, 10, 11, 12])
    def test_out_of_season_the_dish_cannot_be_served(self, month):
        model, cell = _apply(month, ROWS)
        assert _forced_off(model, cell, 'mango_burfi'), (
            f'month {month} is outside March-June and the mango was still '
            f'servable')

    def test_the_dish_beside_it_is_untouched(self):
        model, cell = _apply(11, ROWS)
        assert not _forced_off(model, cell, 'gulab_jamun')


class TestWhatCountsAsAMango:
    """The selector, against the real lists. `key_ingredient` leads because it
    is the only thing that works outside Hindi."""

    @pytest.mark.parametrize('city_file,city', OWNERS)
    def test_it_matches_real_dishes_in_every_city(self, city_file, city):
        from src.ontology import repository
        m = SelectorFrequencyRule._parse_matcher(_config(city_file)['selector'])
        df, _ = repository.menu_data(city)
        df = df.copy()
        df.columns = [str(c).strip().lower() for c in df.columns]
        hits = {str(r['item']).strip().lower() for _i, r in df.iterrows()
                if SelectorFrequencyRule._matches(r, m)}
        assert hits, f'{city}: the mango selector matches nothing (note 9)'

    def test_a_mangodi_is_not_a_mango(self):
        """A mangodi is a dried moong-dal dumpling. NCR carries five of them,
        and a substring match on "mango" takes all five off the menu for eight
        months of the year — the `akki` inside `sabakki` trap again."""
        m = SelectorFrequencyRule._parse_matcher(_config()['selector'])
        for name in ('mangodi', 'mangodi_aloo', 'mangodi_gravy',
                     'mangodi_ki_sabzi', 'aloo_mangodi_ki_sabzi'):
            row = pd.Series({'item': name, 'key_ingredient': 'moong_dal'})
            assert not SelectorFrequencyRule._matches(row, m), name

    def test_the_regional_names_are_caught(self):
        """`mavinakayi` (Kannada), `mangai` (Tamil), `aam` (Hindi) — eight real
        dishes a match on the English word would never find, which is why the
        column leads and the name is only the backstop."""
        m = SelectorFrequencyRule._parse_matcher(_config()['selector'])
        for name in ('mavinakayi_chitranna', 'masala_mangai_sadam', 'aam_panna',
                     'aam_ras', 'tropical_tango'):
            row = pd.Series({'item': name, 'key_ingredient': 'mango'})
            assert SelectorFrequencyRule._matches(row, m), name


class TestTheConfigCannotLoadWrong:
    def test_a_misspelled_month_is_rejected(self):
        """Note 9's expensive failure. Dropping the bad token quietly would
        leave FEWER allowed months than the author wrote, which bans MORE than
        they asked for and reads as working."""
        r = SelectorFrequencyRule({
            'name': 'x', 'type': 'selector_frequency',
            'selector': {'key_ingredient': 'mango'},
            'allowed_months': ['march', 'smarch', 13]})
        errs = r.validation_errors()
        assert any('allowed_months' in e for e in errs), errs

    def test_names_numbers_and_abbreviations_all_work(self):
        for spec in (['march', 'april'], ['mar', 'apr'], [3, 4], ['3', '4']):
            r = SelectorFrequencyRule({
                'name': 'x', 'type': 'selector_frequency',
                'selector': {'key_ingredient': 'mango'}, 'allowed_months': spec})
            assert r.allowed_months == {3, 4}, spec
            assert r.validation_errors() == []

    def test_allowed_months_stands_alone(self):
        """"Mango only in season" is a complete rule with no count in it."""
        assert SelectorFrequencyRule(_config()).validation_errors() == []

    @pytest.mark.parametrize('city_file,_city', OWNERS)
    def test_every_city_that_ships_a_ruleset_carries_it(self, city_file, _city):
        """Universal was the instruction. Hyderabad and NCR extend Bangalore."""
        assert _config(city_file)['allowed_months'] == [
            'march', 'april', 'may', 'june']


class TestItDegradesRatherThanStarving:
    def test_a_slot_with_nothing_but_mango_keeps_it_and_says_so(self, caplog):
        """Out of season beats nothing on the plate. The stand-down is stamped
        so the explanation names the rule that did not hold (note 31)."""
        with caplog.at_level(logging.INFO, logger='src.menu_rules'):
            model, cell = _apply(11, [_dish('mango_burfi', 'mango'),
                                      _dish('mango_kulfi', 'mango')])
        assert not _forced_off(model, cell, 'mango_burfi')
        stamped = [r for r in caplog.records if getattr(r, RELAXATION, None)]
        assert [getattr(r, RELAXATION) for r in stamped] == [RULE_NAME]


def test_every_city_still_plans_out_of_season(fake_supabase):
    """The risk a solve can actually speak to. Mango is 0.6-1.5% of each list
    and at worst 9.3% of one slot (NCR's welcome drinks), so nothing should
    starve — measured here rather than asserted, because 'no mango in November'
    read off a menu passes whether the rule exists or not.
    """
    from api.app import app
    from tests.client_fixtures import CLIENTS
    for name in ('Zscaler', 'Corning Chakan', 'Airtel Noida'):
        fake_supabase.seed('clients', [dict(next(c for c in CLIENTS
                                                 if c['name'] == name))])
        app.config['TESTING'] = True
        with app.test_client() as c:
            resp = c.post('/api/v1/plan', json={
                'client_name': name, 'start_date': '2026-11-02',
                'num_days': 5, 'time_limit_seconds': 40})
        assert resp.status_code == 200, (name, resp.get_json())


if __name__ == '__main__':      # a runnable check without pytest
    raise SystemExit(pytest.main([__file__, '-q']))
