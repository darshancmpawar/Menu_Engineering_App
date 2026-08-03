"""Tests for SoftPreferenceRule (Phase-4 soft-rule framework).

Config validation plus CP-SAT behaviour: with the penalty in the objective the
solver must prefer the arrangement the rule encodes (premiums apart, no
consecutive regional repeat, varied attribute). Soft rules never constrain
feasibility, so these assert *preference*, not hard bans.
"""

import datetime as dt

import pandas as pd
from ortools.sat.python import cp_model

from src.menu_rules.soft_preference_rule import SoftPreferenceRule
from src.menu_rules.base_menu_rule import MenuRuleType, MenuRuleSeverity


class _FakeCell:
    def __init__(self, d_idx, base_slot, rows, x_vars):
        self.d_idx = d_idx
        self.date = dt.date(2026, 3, 23) + dt.timedelta(days=d_idx)
        self.slot_id = f'{base_slot}__1'
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
    rows = [pd.Series({'item': f'{base_slot}_{di}_{i}', **it}) for i, it in enumerate(items)]
    xs = [model.NewBoolVar(f'x_{di}_{base_slot}_{i}') for i in range(len(items))]
    model.Add(sum(xs) == 1)
    return _FakeCell(di, base_slot, rows, xs)


def _ctx(cells, n_days):
    return {
        'cells': cells,
        'dates': [dt.date(2026, 3, 23) + dt.timedelta(days=i) for i in range(n_days)],
        'link_any_fn': _link_any,
    }


def _maximize(model, terms):
    model.Maximize(sum(terms))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5
    return solver, solver.Solve(model)


class TestConfig:
    def test_type_and_severity(self):
        r = SoftPreferenceRule({'name': 'x', 'mode': 'avoid_consecutive',
                                'base_slot': 'rice', 'selector': {'flag': 'f'}})
        assert r.rule_type == MenuRuleType.SOFT_PREFERENCE
        assert r.severity == MenuRuleSeverity.SOFT
        assert r.validate_config()

    def test_bad_mode(self):
        assert not SoftPreferenceRule({'name': 'x', 'mode': 'nope'}).validate_config()

    def test_different_day_needs_both_selectors(self):
        assert not SoftPreferenceRule({
            'name': 'x', 'mode': 'different_day',
            'selector_a': {'flag': 'a'}}).validate_config()

    def test_avoid_consecutive_needs_selector(self):
        assert not SoftPreferenceRule({
            'name': 'x', 'mode': 'avoid_consecutive', 'base_slot': 'rice'}).validate_config()

    def test_attr_repeat_needs_group_by(self):
        assert not SoftPreferenceRule({
            'name': 'x', 'mode': 'avoid_attribute_repeat', 'base_slot': 'veg_gravy'}).validate_config()

    def test_negative_weight_rejected(self):
        assert not SoftPreferenceRule({
            'name': 'x', 'mode': 'avoid_consecutive', 'selector': {'flag': 'f'},
            'weight': -1}).validate_config()

    def test_bad_priority_rejected(self):
        assert not SoftPreferenceRule({
            'name': 'x', 'mode': 'avoid_consecutive', 'selector': {'flag': 'f'},
            'priority': 'urgent'}).validate_config()

    def test_priority_maps_to_tier_weight(self):
        from src.constants import OBJECTIVE_TIER_WEIGHTS
        for pri in ('high', 'medium', 'low'):
            r = SoftPreferenceRule({'name': 'x', 'mode': 'avoid_consecutive',
                                    'selector': {'flag': 'f'}, 'priority': pri})
            assert r.weight == OBJECTIVE_TIER_WEIGHTS[pri]
        # explicit weight overrides the tier
        r = SoftPreferenceRule({'name': 'x', 'mode': 'avoid_consecutive',
                                'selector': {'flag': 'f'}, 'priority': 'high', 'weight': 5})
        assert r.weight == 5

    def test_apply_is_noop(self):
        # objective-only rule: apply must be safe and do nothing
        SoftPreferenceRule({'name': 'x', 'mode': 'avoid_consecutive',
                            'selector': {'flag': 'f'}}).apply(None, {}, None, {})


class TestBehaviour:
    def test_premiums_pushed_to_different_days(self):
        model = cp_model.CpModel()
        # exactly one premium gravy and one premium dry across 2 days; solver
        # chooses which day each lands on.
        g0 = _cell(model, 0, 'veg_gravy', [{'is_premium_gravy': 1}, {'is_premium_gravy': 0}])
        g1 = _cell(model, 1, 'veg_gravy', [{'is_premium_gravy': 1}, {'is_premium_gravy': 0}])
        d0 = _cell(model, 0, 'veg_dry', [{'is_premium_veg_dry': 1}, {'is_premium_veg_dry': 0}])
        d1 = _cell(model, 1, 'veg_dry', [{'is_premium_veg_dry': 1}, {'is_premium_veg_dry': 0}])
        model.Add(g0.x_vars[0] + g1.x_vars[0] == 1)   # one premium gravy in the week
        model.Add(d0.x_vars[0] + d1.x_vars[0] == 1)   # one premium dry in the week
        rule = SoftPreferenceRule({
            'name': 'prem', 'mode': 'different_day', 'weight': 1000,
            'selector_a': {'flag': 'is_premium_gravy'}, 'base_slot_a': 'veg_gravy',
            'selector_b': {'flag': 'is_premium_veg_dry'}, 'base_slot_b': 'veg_dry'})
        terms = rule.get_objective_terms(model, _ctx([g0, g1, d0, d1], 2))
        solver, status = _maximize(model, terms)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        gravy_day = 0 if solver.Value(g0.x_vars[0]) else 1
        dry_day = 0 if solver.Value(d0.x_vars[0]) else 1
        assert gravy_day != dry_day

    def test_avoid_consecutive_regional_rice(self):
        model = cp_model.CpModel()
        # day0 rice can only be north; day1 may be north or south.
        r0 = _cell(model, 0, 'rice', [{'cuisine_family': 'north_indian'}])
        r1 = _cell(model, 1, 'rice',
                   [{'cuisine_family': 'north_indian'}, {'cuisine_family': 'south_indian'}])
        rule = SoftPreferenceRule({
            'name': 'nc', 'mode': 'avoid_consecutive', 'weight': 1000,
            'base_slot': 'rice', 'selector': {'cuisine_family': 'north_indian'}})
        terms = rule.get_objective_terms(model, _ctx([r0, r1], 2))
        solver, status = _maximize(model, terms)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        assert solver.Value(r1.x_vars[1]) == 1   # day1 picks south to break the run

    def test_high_priority_wins_over_medium(self):
        # 3 days of rice; day1 is the only free choice. Picking north on day1
        # makes north consecutive (violates the HIGH rule); picking south makes
        # south consecutive (violates the MEDIUM rule). Lexicographic tiers must
        # make the solver sacrifice the medium rule to protect the high one.
        model = cp_model.CpModel()
        r0 = _cell(model, 0, 'rice', [{'cuisine_family': 'north_indian'}])
        r1 = _cell(model, 1, 'rice',
                   [{'cuisine_family': 'north_indian'}, {'cuisine_family': 'south_indian'}])
        r2 = _cell(model, 2, 'rice', [{'cuisine_family': 'south_indian'}])
        cells = [r0, r1, r2]
        high = SoftPreferenceRule({
            'name': 'hi', 'mode': 'avoid_consecutive', 'priority': 'high',
            'base_slot': 'rice', 'selector': {'cuisine_family': 'north_indian'}})
        med = SoftPreferenceRule({
            'name': 'md', 'mode': 'avoid_consecutive', 'priority': 'medium',
            'base_slot': 'rice', 'selector': {'cuisine_family': 'south_indian'}})
        ctx = _ctx(cells, 3)
        terms = high.get_objective_terms(model, ctx) + med.get_objective_terms(model, ctx)
        solver, status = _maximize(model, terms)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        # day1 goes south: the high (north) rule is protected at the medium
        # rule's expense.
        assert solver.Value(r1.x_vars[1]) == 1

    def test_avoid_attribute_repeat_varies_key_ingredient(self):
        model = cp_model.CpModel()
        v0 = _cell(model, 0, 'veg_gravy', [{'key_ingredient': 'potato'}])
        v1 = _cell(model, 1, 'veg_gravy',
                   [{'key_ingredient': 'potato'}, {'key_ingredient': 'tomato'}])
        rule = SoftPreferenceRule({
            'name': 'var', 'mode': 'avoid_attribute_repeat', 'weight': 1000,
            'base_slot': 'veg_gravy', 'group_by': 'key_ingredient'})
        terms = rule.get_objective_terms(model, _ctx([v0, v1], 2))
        solver, status = _maximize(model, terms)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        assert solver.Value(v1.x_vars[1]) == 1   # day1 picks tomato, not another potato


class TestPreferDayTypes:
    """`prefer_day_types` — the selector belongs on these themes; other days are
    penalised, not forbidden.

    The hard equivalent is `selector_frequency.allowed_day_types`, and it would
    forbid the dish outright — a counter themed chinese every weekday would then
    never serve paneer at all. The client's ask is "prefer mix/south/north, fall
    back to the others", so the others must stay legal.
    """

    def _ctx_with_themes(self, cells, themes):
        ctx = _ctx(cells, len(themes))
        ctx['day_types'] = list(themes)
        return ctx

    def test_requires_selector_and_day_types(self):
        assert not SoftPreferenceRule({
            'name': 'x', 'mode': 'prefer_day_types',
            'day_types': ['north']}).validate_config()
        assert not SoftPreferenceRule({
            'name': 'x', 'mode': 'prefer_day_types',
            'selector': {'key_ingredient': 'paneer'}}).validate_config()
        rule = SoftPreferenceRule({
            'name': 'x', 'mode': 'prefer_day_types',
            'selector': {'key_ingredient': 'paneer'}, 'day_types': ['north']})
        assert rule.validate_config(), rule.validation_errors()

    def test_day_types_are_case_insensitive(self):
        rule = SoftPreferenceRule({
            'name': 'x', 'mode': 'prefer_day_types',
            'selector': {'key_ingredient': 'paneer'},
            'day_types': ['MIX', ' South ', 'north']})
        assert rule.day_types == {'mix', 'south', 'north'}

    def test_paneer_moves_onto_a_preferred_day(self):
        """Two days, one paneer to place: it must land on the north day, not the
        biryani day."""
        model = cp_model.CpModel()
        # Each day's gravy is paneer or not; exactly one paneer across the two.
        d0 = _cell(model, 0, 'veg_gravy',
                   [{'key_ingredient': 'paneer'}, {'key_ingredient': 'potato'}])
        d1 = _cell(model, 1, 'veg_gravy',
                   [{'key_ingredient': 'paneer'}, {'key_ingredient': 'potato'}])
        model.Add(d0.x_vars[0] + d1.x_vars[0] == 1)
        rule = SoftPreferenceRule({
            'name': 'pref', 'mode': 'prefer_day_types', 'weight': 1000,
            'base_slot': 'veg_gravy', 'selector': {'key_ingredient': 'paneer'},
            'day_types': ['mix', 'south', 'north']})
        ctx = self._ctx_with_themes([d0, d1], ['biryani', 'north'])
        solver, status = _maximize(model, rule.get_objective_terms(model, ctx))
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        assert solver.Value(d1.x_vars[0]) == 1, "paneer should be on the north day"
        assert solver.Value(d0.x_vars[0]) == 0

    def test_off_theme_is_allowed_when_it_is_the_only_option(self):
        """Soft, not hard: with every day off-theme the dish still gets placed."""
        model = cp_model.CpModel()
        d0 = _cell(model, 0, 'veg_gravy', [{'key_ingredient': 'paneer'}])
        rule = SoftPreferenceRule({
            'name': 'pref', 'mode': 'prefer_day_types', 'weight': 1000,
            'base_slot': 'veg_gravy', 'selector': {'key_ingredient': 'paneer'},
            'day_types': ['mix', 'south', 'north']})
        ctx = self._ctx_with_themes([d0], ['chinese'])
        terms = rule.get_objective_terms(model, ctx)
        solver, status = _maximize(model, terms)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        assert solver.Value(d0.x_vars[0]) == 1
        assert terms, "an off-theme day must contribute a penalty term"

    def test_no_penalty_term_when_every_day_is_preferred(self):
        model = cp_model.CpModel()
        d0 = _cell(model, 0, 'veg_gravy', [{'key_ingredient': 'paneer'}])
        rule = SoftPreferenceRule({
            'name': 'pref', 'mode': 'prefer_day_types',
            'base_slot': 'veg_gravy', 'selector': {'key_ingredient': 'paneer'},
            'day_types': ['north']})
        ctx = self._ctx_with_themes([d0], ['north'])
        assert rule.get_objective_terms(model, ctx) == []
