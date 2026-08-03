"""Tests for SameDayExclusionRule and the `any_of` composite selector.

The rule the client asked for: no soya, baby corn, chole or mushroom on a paneer
day, in every city. Two things had to exist for it —

* ``any_of``, so one selector can name several ingredients across both flag and
  text columns (``key_ingredient: soy`` OR ``flag: is_chana_gravy`` OR …).
* the rule itself, HARD, because "don't serve them together" is a constraint and
  a soft penalty can always be outbid.

The one relaxation is arithmetic, not a fallback: a day where BOTH sides are
forced is skipped, since no choice satisfies the rule and enforcing it would turn
a reportable impossibility into a bare INFEASIBLE.
"""

import datetime as dt

import pandas as pd
import pytest
from ortools.sat.python import cp_model

from src.menu_rules.base_menu_rule import MenuRuleType
from src.menu_rules.same_day_exclusion_rule import SameDayExclusionRule
from src.menu_rules.selector_frequency_rule import SelectorFrequencyRule

PANEER = {'selector': {'key_ingredient': 'paneer'}}
EXCLUDE_FOUR = {'exclude': {'any_of': [
    {'key_ingredient': 'soy'},
    {'key_ingredient': 'baby_corn'},
    {'flag': 'is_chana_gravy'},
    {'key_ingredient': 'mushroom'},
]}}


class _FakeCell:
    def __init__(self, d_idx, base_slot, rows, x_vars):
        self.d_idx = d_idx
        self.date = dt.date(2026, 8, 3) + dt.timedelta(days=d_idx)
        self.slot_id = base_slot
        self.base_slot = base_slot
        self.cand_rows = rows
        self.x_vars = x_vars


def _link_any(model, lits, y):
    if not lits:
        model.Add(y == 0)
        return
    model.Add(sum(lits) >= y)
    for lit in lits:
        model.Add(lit <= y)


def _cell(model, di, base_slot, items):
    rows = [pd.Series({'item': f'{base_slot}_{di}_{i}', **it})
            for i, it in enumerate(items)]
    xs = [model.NewBoolVar(f'x_{di}_{base_slot}_{i}') for i in range(len(items))]
    model.Add(sum(xs) == 1)
    return _FakeCell(di, base_slot, rows, xs)


def _ctx(cells, n_days):
    return {
        'cells': cells,
        'dates': [dt.date(2026, 8, 3) + dt.timedelta(days=i) for i in range(n_days)],
        'link_any_fn': _link_any,
    }


def _rule(**over):
    cfg = {'name': 'no_pair', 'type': 'same_day_exclusion', **PANEER, **EXCLUDE_FOUR}
    cfg.update(over)
    return SameDayExclusionRule(cfg)


def _solve(model):
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5
    return solver, solver.Solve(model)


class TestAnyOfMatcher:
    def test_matches_across_flag_and_text_columns(self):
        m = SelectorFrequencyRule._parse_matcher(EXCLUDE_FOUR['exclude'])
        assert m[0] == 'any_of' and len(m[1]) == 4
        assert SelectorFrequencyRule._matches({'key_ingredient': 'soy'}, m)
        assert SelectorFrequencyRule._matches({'key_ingredient': 'baby_corn'}, m)
        assert SelectorFrequencyRule._matches({'is_chana_gravy': 1}, m)
        assert SelectorFrequencyRule._matches({'key_ingredient': 'mushroom'}, m)
        assert not SelectorFrequencyRule._matches({'key_ingredient': 'potato'}, m)
        assert not SelectorFrequencyRule._matches({'is_chana_gravy': 0}, m)

    def test_accepts_a_single_selector_not_in_a_list(self):
        m = SelectorFrequencyRule._parse_matcher(
            {'any_of': {'key_ingredient': 'soy'}})
        assert SelectorFrequencyRule._matches({'key_ingredient': 'soy'}, m)

    def test_empty_or_unparseable_yields_none(self):
        assert SelectorFrequencyRule._parse_matcher({'any_of': []}) is None
        assert SelectorFrequencyRule._parse_matcher({'any_of': [{}]}) is None

    def test_existing_selector_forms_still_work(self):
        """`any_of` is additive — the single-key and any_flag forms are untouched."""
        m = SelectorFrequencyRule._parse_matcher({'key_ingredient': 'paneer'})
        assert SelectorFrequencyRule._matches({'key_ingredient': 'paneer'}, m)
        m = SelectorFrequencyRule._parse_matcher({'any_flag': ['a', 'b']})
        assert SelectorFrequencyRule._matches({'b': 1}, m)


class TestConfig:
    def test_rule_type(self):
        assert _rule().rule_type == MenuRuleType.SAME_DAY_EXCLUSION

    @pytest.mark.parametrize('cfg', [
        {'name': 'x', 'type': 'same_day_exclusion'},
        {'name': 'x', 'type': 'same_day_exclusion', **PANEER},
        {'name': 'x', 'type': 'same_day_exclusion', **EXCLUDE_FOUR},
    ])
    def test_both_sides_are_required(self, cfg):
        assert not SameDayExclusionRule(cfg).validate_config()

    def test_valid_config(self):
        r = _rule()
        assert r.validate_config(), r.validation_errors()

    def test_loader_registers_the_type(self):
        from src.menu_rules.menu_rule_loader import MenuRuleLoader
        rules = MenuRuleLoader().load_from_dict({'rules': [
            {'name': 'x', 'type': 'same_day_exclusion', **PANEER, **EXCLUDE_FOUR},
        ]})
        assert len(rules) == 1
        assert isinstance(rules[0], SameDayExclusionRule)


class TestConstraint:
    def test_paneer_day_cannot_also_serve_soya(self):
        model = cp_model.CpModel()
        gravy = _cell(model, 0, 'veg_gravy', [{'key_ingredient': 'paneer'}])
        dry = _cell(model, 0, 'veg_dry',
                    [{'key_ingredient': 'soy'}, {'key_ingredient': 'potato'}])
        _rule().apply(model, {}, None, _ctx([gravy, dry], 1))
        solver, status = _solve(model)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        assert solver.Value(dry.x_vars[1]) == 1, "must pick potato, not soya"

    def test_it_works_in_the_other_direction_too(self):
        """The exclusion is symmetric: a soya day cannot add paneer either."""
        model = cp_model.CpModel()
        dry = _cell(model, 0, 'veg_dry', [{'key_ingredient': 'soy'}])
        gravy = _cell(model, 0, 'veg_gravy',
                      [{'key_ingredient': 'paneer'}, {'key_ingredient': 'potato'}])
        _rule().apply(model, {}, None, _ctx([gravy, dry], 1))
        solver, status = _solve(model)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        assert solver.Value(gravy.x_vars[1]) == 1

    def test_chana_gravy_counts_as_chole(self):
        model = cp_model.CpModel()
        gravy = _cell(model, 0, 'veg_gravy',
                      [{'is_chana_gravy': 1}, {'key_ingredient': 'potato'}])
        dry = _cell(model, 0, 'veg_dry', [{'key_ingredient': 'paneer'}])
        _rule().apply(model, {}, None, _ctx([gravy, dry], 1))
        solver, status = _solve(model)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        assert solver.Value(gravy.x_vars[1]) == 1

    def test_other_days_are_untouched(self):
        """The constraint is per day — a soya on Tuesday is fine when paneer is on
        Monday."""
        model = cp_model.CpModel()
        mon_gravy = _cell(model, 0, 'veg_gravy', [{'key_ingredient': 'paneer'}])
        tue_dry = _cell(model, 1, 'veg_dry', [{'key_ingredient': 'soy'}])
        _rule().apply(model, {}, None, _ctx([mon_gravy, tue_dry], 2))
        solver, status = _solve(model)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        assert solver.Value(tue_dry.x_vars[0]) == 1

    def test_unrelated_pairs_are_not_constrained(self):
        """Only pairings WITH paneer are excluded — soya beside chole is legal."""
        model = cp_model.CpModel()
        gravy = _cell(model, 0, 'veg_gravy', [{'is_chana_gravy': 1}])
        dry = _cell(model, 0, 'veg_dry', [{'key_ingredient': 'soy'}])
        _rule().apply(model, {}, None, _ctx([gravy, dry], 1))
        solver, status = _solve(model)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    def test_base_slot_narrows_the_selector_side(self):
        model = cp_model.CpModel()
        gravy = _cell(model, 0, 'veg_gravy', [{'key_ingredient': 'paneer'}])
        dry = _cell(model, 0, 'veg_dry', [{'key_ingredient': 'soy'}])
        # Only `salad` paneer is excluded, so this gravy/dry pair is untouched.
        _rule(base_slot='salad').apply(model, {}, None, _ctx([gravy, dry], 1))
        solver, status = _solve(model)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        assert solver.Value(dry.x_vars[0]) == 1


class TestRelaxation:
    def test_a_day_with_both_sides_forced_is_skipped_not_made_infeasible(self):
        """Every candidate in one slot is paneer and every candidate in another is
        soya: no choice satisfies the rule, so it steps aside rather than
        producing a bare INFEASIBLE with nothing pointing at the cause.
        """
        model = cp_model.CpModel()
        gravy = _cell(model, 0, 'veg_gravy', [{'key_ingredient': 'paneer'}])
        dry = _cell(model, 0, 'veg_dry', [{'key_ingredient': 'soy'}])
        _rule().apply(model, {}, None, _ctx([gravy, dry], 1))
        solver, status = _solve(model)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        assert solver.Value(gravy.x_vars[0]) == 1
        assert solver.Value(dry.x_vars[0]) == 1

    def test_one_side_forced_is_still_enforced(self):
        """Only the BOTH-forced case relaxes. A forced paneer with a choosable
        veg dry must still push the soya out."""
        model = cp_model.CpModel()
        gravy = _cell(model, 0, 'veg_gravy', [{'key_ingredient': 'paneer'}])
        dry = _cell(model, 0, 'veg_dry',
                    [{'key_ingredient': 'soy'}, {'key_ingredient': 'potato'}])
        _rule().apply(model, {}, None, _ctx([gravy, dry], 1))
        solver, status = _solve(model)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        assert solver.Value(dry.x_vars[1]) == 1

    def test_absent_side_adds_no_constraint(self):
        model = cp_model.CpModel()
        gravy = _cell(model, 0, 'veg_gravy', [{'key_ingredient': 'paneer'}])
        dry = _cell(model, 0, 'veg_dry', [{'key_ingredient': 'potato'}])
        _rule().apply(model, {}, None, _ctx([gravy, dry], 1))
        solver, status = _solve(model)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)


class TestDiagnose:
    def _ctx(self, pools):
        from src.menu_rules.base_menu_rule import DiagnoseContext
        from src.solver.menu_solver import SolverConfig
        d = dt.date(2026, 8, 3)
        return DiagnoseContext(
            pools=pools, dates=[d], day_types={d: 'north'},
            cfg=SolverConfig(days=1, start_date=d), df=pd.DataFrame(),
            banned_by_date={}, ricebread_ban_day={}, skip_cells=set(),
            client_cfg=None, active_base_slots=list(pools),
        )

    def test_quiet_when_both_sides_match_items(self):
        pools = {
            'veg_gravy': pd.DataFrame([{'item': 'p', 'key_ingredient': 'paneer'}]),
            'veg_dry': pd.DataFrame([{'item': 's', 'key_ingredient': 'soy'}]),
        }
        assert _rule().diagnose(self._ctx(pools)) == []

    def test_reports_an_inert_exclusion(self):
        """Pune carries no mushroom dish; a city with none of the four at all
        should say so rather than look enforced."""
        pools = {
            'veg_gravy': pd.DataFrame([{'item': 'p', 'key_ingredient': 'paneer'}]),
            'veg_dry': pd.DataFrame([{'item': 'x', 'key_ingredient': 'potato'}]),
        }
        diags = _rule().diagnose(self._ctx(pools))
        assert len(diags) == 1
        assert diags[0].severity.value == 'info'
        assert 'inert' in diags[0].message


class TestShippedInBothCities:
    """The client's rule is "all cities", so both rulesets must carry it."""

    @pytest.mark.parametrize('city', ['Bangalore', 'Pune'])
    def test_both_paneer_rules_are_present_and_valid(self, city):
        from src.menu_rules.menu_rule_loader import MenuRuleLoader
        rules = {r.name: r for r in MenuRuleLoader().load_for_city(city)}
        for name in ('paneer_prefers_mix_south_north_days',
                     'paneer_not_with_soya_babycorn_chole_mushroom'):
            assert name in rules, sorted(rules)
            assert rules[name].validate_config(), rules[name].validation_errors()

    @pytest.mark.parametrize('city', ['Bangalore', 'Pune'])
    def test_the_exclusion_matches_real_items_in_each_city(self, city):
        """A selector that matches nothing is a rule that does nothing. Mushroom
        is absent from Pune, which is why the four are an `any_of` rather than
        four separate rules."""
        from api.config import city_excel_path
        from src.menu_rules.menu_rule_loader import MenuRuleLoader
        from src.preprocessor.data_cleanser import DataCleanser
        from src.preprocessor.excel_reader import ExcelReader

        df = DataCleanser(ExcelReader(city_excel_path(city)).read()).clean()
        rule = next(r for r in MenuRuleLoader().load_for_city(city)
                    if r.name == 'paneer_not_with_soya_babycorn_chole_mushroom')
        n_sel = sum(1 for _i, r in df.iterrows()
                    if SelectorFrequencyRule._matches(r, rule._sel))
        n_exc = sum(1 for _i, r in df.iterrows()
                    if SelectorFrequencyRule._matches(r, rule._exc))
        assert n_sel > 0, f"{city}: nothing matches the paneer selector"
        assert n_exc > 0, f"{city}: nothing matches the exclude selector"
