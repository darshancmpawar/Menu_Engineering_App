"""Seasonal high-risk vegetables: the sheet, the matcher, and the rule.

The sheet is free text, so the parser is pinned on the rows that tripped it;
the matcher on the names that decide whether a dish is banned; the rule on
what the product decided: red removed, tomato kept out of salads, pins kept,
yellow avoided, an empty slot caught before the solver.
"""
import datetime as dt
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from ortools.sat.python import cp_model

from scripts import build_seasonal_bans as builder
from src.menu_rules.base_menu_rule import DiagnosticSeverity
from src.menu_rules.menu_rule_loader import MenuRuleLoader
from src.menu_rules.seasonal_ban_rule import SeasonalBanRule
from src.seasonal.bans import VegetableMatcher, bans_by_month, bans_for, region_for_city

ROOT = Path(__file__).resolve().parents[2]
SHEET = ROOT / 'data' / 'raw' / 'seasonal' / 'high_risk_vegetables_2026.xlsx'
OCT = dt.date(2026, 10, 26)


# --- the sheet --------------------------------------------------------------

class TestParser:
    def test_the_committed_file_is_what_the_sheet_says(self):
        """Nobody hand-edits the JSON: regenerating from the sheet gives the same file."""
        built, _review = builder.build(SHEET, 2026)
        committed = json.loads((ROOT / 'data/configs/seasonal_bans/2026.json').read_text())
        assert built['months'] == committed['months']

    def test_every_fragment_of_the_sheet_is_recognised(self):
        _built, review = builder.build(SHEET, 2026)
        assert not [r for r in review if 'not recognised' in r], review

    @pytest.fixture(scope='class')
    def spellings(self):
        return builder._spellings(json.loads(builder.VOCAB_PATH.read_text()))

    def test_typos_and_local_names(self, spellings):
        found, left = builder.parse_list('Vegetables: Bindi, Brijal, Cauli flower, Bitter guard', spellings)
        assert found == {'bhindi', 'brinjal', 'cauliflower', 'bitter gourd'} and left == []

    def test_small_tomato_is_not_every_tomato(self, spellings):
        found, _ = builder.parse_list('Vegetables: Cabbage, Tomato small', spellings)
        assert found == {'cabbage', 'small tomato'}

    def test_frozen_corns_and_peas_is_two_vegetables(self, spellings):
        found, _ = builder.parse_list('Vegetables: Frozen corns and peas', spellings)
        assert found == {'corn', 'green peas'}

    def test_a_missing_comma_still_reads_both(self, spellings):
        found, _ = builder.parse_list('Vegetables: Bhindi coriander, curry leaves', spellings)
        assert {'bhindi', 'coriander', 'curry leaves'} <= found

    def test_unknown_words_are_reported_not_dropped(self, spellings):
        _found, left = builder.parse_list('Vegetables: Cabbage, Zucchinis', spellings)
        assert left == ['zucchinis']

    def test_notes_are_split_out_and_the_salad_rule_found(self):
        _text, notes = builder.split_notes(
            'Vegetables: Tomato  Note: Use tomato purée in place of whole tomatoes.  Do not use Tomatoes in the salad.')
        assert notes == ['Use tomato purée in place of whole tomatoes.', 'Do not use Tomatoes in the salad.']

    def test_red_wins_over_yellow(self):
        may = bans_for('Bangalore', dt.date(2026, 5, 4))
        assert 'brinjal' in may.red and 'brinjal' not in may.yellow


# --- which list applies --------------------------------------------------------

class TestLookup:
    @pytest.mark.parametrize('city,region', [('Bangalore', 'Karnataka'), ('Hyderabad', 'AP & Telangana'),
                                             ('Chennai', 'Tamilnadu'), ('Pune', 'Maharashtra'), ('NCR', 'North')])
    def test_each_city_maps_to_its_region(self, city, region):
        assert region_for_city(city, 2026) == region

    def test_october_karnataka(self):
        b = bans_for('Bangalore', OCT)
        assert b.label == 'October 2026'
        assert b.red == {'bhindi', 'brinjal', 'broccoli', 'cabbage', 'cauliflower', 'cucumber', 'lettuce', 'muskmelon'}
        assert 'tomato' in b.yellow and not b.salad_bans

    def test_a_plan_across_a_month_end_gets_both_months(self):
        months = bans_by_month('Bangalore', [dt.date(2026, 10, 30), dt.date(2026, 11, 2)])
        assert [m.key for m in months] == ['2026-10', '2026-11']

    def test_unknown_city_has_no_list(self):
        assert bans_for('Atlantis', OCT) is None


# --- which dishes it hits ------------------------------------------------------

def _df(rows):
    return pd.DataFrame(rows, columns=['item', 'key_ingredient', 'is_leafy_based_dish'])


class TestMatcher:
    @pytest.fixture(scope='class')
    def m(self):
        return VegetableMatcher()

    @pytest.mark.parametrize('name,key,expected', [
        ('aloo_gobi', 'potato', {'cauliflower'}),              # the field says potato, the name says gobi
        ('patta_gobi_sabzi', 'cabbage', {'cabbage'}),          # patta gobi is cabbage, not cauliflower
        ('aloo_baingan_bharta', 'potato', {'brinjal'}),
        ('bendakaya_fry', 'okra', {'bhindi'}),
        ('dosakai_sambar', 'dal', {'cucumber'}),
        ('kosambari', 'moong_dal', set()),                     # "kose" is cabbage; kosambari is not
        ('baby_corn_masala', 'baby_corn', set()),              # baby corn is a safe alternative, not corn
        ('chickpea_salad', 'chickpea', set()),                 # chickpeas are not green peas
        ('kidney_beans_curry', 'kidney_bean', set()),          # rajma is not "beans" on the list
    ])
    def test_names_that_decide_a_ban(self, m, name, key, expected):
        assert m.vegetables_in(name, key, ['cauliflower', 'cabbage', 'brinjal', 'bhindi', 'cucumber',
                                           'corn', 'green peas', 'beans']) == expected

    def test_leafy_group_uses_the_workbook_flag(self, m):
        df = _df([('mystery_saag_bowl', 'paneer', 1), ('plain_dal', 'dal', 0)])
        assert m.mask(df, ['leafy vegetables']).tolist() == [True, False]

    def test_mixed_vegetables_are_never_matched(self, m):
        df = _df([('subz_jalfrezi', 'mixed_vegetables', 0)])
        assert not m.mask(df, sorted(bans_for('Bangalore', OCT).red)).any()


# --- the rule ------------------------------------------------------------------

def _rule(red=(), yellow=(), salad_bans=(), dates=(OCT,)):
    return SeasonalBanRule({'type': 'seasonal_ban', 'name': 'seasonal_vegetables', 'by_date': {
        d.isoformat(): {'month': d.isoformat()[:7], 'red': list(red), 'yellow': list(yellow),
                        'salad_bans': list(salad_bans)} for d in dates}})


POOL = _df([('aloo_gobi', 'potato', 0), ('green_salad', 'lettuce', 0), ('carrot_beetroot_salad', 'carrot', 0),
            ('cucumber_tomato_salad', 'cucumber', 0), ('tomato_rice', 'tomato', 0), ('jeera_rice', 'rice', 0)])


def _ctx(forced=None):
    return {'cfg': SimpleNamespace(forced_items=forced or {})}


class TestRule:
    def test_it_is_a_registered_rule_type(self):
        rule = MenuRuleLoader()._create_rule({'type': 'seasonal_ban', 'name': 's',
                                              'by_date': {OCT.isoformat(): {'red': ['cabbage']}}})
        assert isinstance(rule, SeasonalBanRule) and rule.validate_config()

    def test_red_list_dishes_are_removed(self):
        out = _rule(red=['cauliflower', 'lettuce']).pre_filter_pool(POOL, OCT, 'veg_dry', 'mix', _ctx())
        assert 'aloo_gobi' not in set(out['item']) and 'green_salad' not in set(out['item'])

    def test_a_pinned_dish_stays(self):
        """The pin is kept; the kitchen makes it without the vegetable."""
        out = _rule(red=['lettuce']).pre_filter_pool(
            POOL, OCT, 'salad', 'mix', _ctx({(OCT, 'salad'): 'green_salad'}))
        assert 'green_salad' in set(out['item'])

    def test_a_pin_on_another_day_does_not_protect_today(self):
        other = OCT + dt.timedelta(days=1)
        out = _rule(red=['lettuce']).pre_filter_pool(
            POOL, OCT, 'salad', 'mix', _ctx({(other, 'salad'): 'green_salad'}))
        assert 'green_salad' not in set(out['item'])

    def test_no_tomato_in_the_salad_slot_only(self):
        rule = _rule(salad_bans=['tomato'])
        salad = rule.pre_filter_pool(POOL, OCT, 'salad', 'mix', _ctx())
        rice = rule.pre_filter_pool(POOL, OCT, 'rice', 'mix', _ctx())
        assert 'cucumber_tomato_salad' not in set(salad['item'])
        assert 'tomato_rice' in set(rice['item'])

    def test_a_date_without_a_list_is_untouched(self):
        out = _rule(red=['lettuce']).pre_filter_pool(POOL, OCT + dt.timedelta(days=9), 'salad', 'mix', _ctx())
        assert len(out) == len(POOL)

    def test_yellow_is_a_penalty_not_a_ban(self):
        rule = _rule(yellow=['tomato'])
        assert len(rule.pre_filter_pool(POOL, OCT, 'rice', 'mix', _ctx())) == len(POOL)
        model = cp_model.CpModel()
        xs = [model.NewBoolVar(n) for n in ('tomato_rice', 'jeera_rice')]
        cell = SimpleNamespace(date=OCT, cand_rows=[POOL.iloc[4], POOL.iloc[5]], x_vars=xs)
        terms = rule.get_objective_terms(model, {'cells': [cell]})
        assert len(terms) == 1
        model.Add(sum(xs) == 1)
        model.Maximize(terms[0])
        solver = cp_model.CpSolver()
        solver.Solve(model)
        assert solver.Value(xs[1]) == 1           # the solver steers to jeera rice

    def test_an_emptied_slot_is_an_error_before_solving(self):
        rule = _rule(red=['lettuce', 'cucumber', 'cauliflower', 'tomato'])
        salads = POOL[POOL['item'].str.contains('salad')].drop(index=[2])
        ctx = SimpleNamespace(dates=[OCT], active_base_slots=['salad'], pools={'salad': salads})
        diags = rule.diagnose(ctx)
        assert diags and diags[0].severity == DiagnosticSeverity.ERROR


class TestAttachedToEveryPlan:
    def test_bangalore_plans_get_the_rule_per_date(self, monkeypatch):
        from src.application.solve_inputs import _apply_seasonal_bans
        monkeypatch.setenv('SEASONAL_BANS_ENABLED', 'true')
        dates = [dt.date(2026, 10, 30), dt.date(2026, 11, 2)]
        rules = _apply_seasonal_bans([], dates, 'Bangalore')
        assert len(rules) == 1 and isinstance(rules[0], SeasonalBanRule)
        assert rules[0].by_date['2026-10-30']['month'] == '2026-10'
        assert 'cabbage' in rules[0].by_date['2026-10-30']['red']
        assert 'cabbage' not in rules[0].by_date['2026-11-02']['red']   # November drops cabbage

    def test_kill_switch(self, monkeypatch):
        from src.application.solve_inputs import _apply_seasonal_bans
        monkeypatch.setenv('SEASONAL_BANS_ENABLED', 'false')
        assert _apply_seasonal_bans([], [OCT], 'Bangalore') == []

    def test_a_city_without_a_region_gets_nothing(self, monkeypatch):
        from src.application.solve_inputs import _apply_seasonal_bans
        monkeypatch.setenv('SEASONAL_BANS_ENABLED', 'true')
        assert _apply_seasonal_bans([], [OCT], 'Atlantis') == []
