"""The plate must not echo itself: same-day distinctness and the N-day gap.

Three additions to `attribute_grouping`, each asserted as what reaches a CELL
rather than as a config value, because every one of them can be configured
correctly and still constrain nothing:

  * `max_cells_per_day` — the veg gravy and the veg dry may not share a key
    ingredient ON ONE PLATE. The pre-existing day-bool encoding structurally
    cannot express this (it collapses "this value is somewhere today" to one
    variable), so a test that only checked the config would have passed while
    the constraint was absent.
  * `min_days_between` — N CLEAR days before a value returns, generalising
    `non_consecutive` (which is exactly N=1).
  * `require_value` — a blank `key_ingredient` is not a candidate, EXCEPT where
    dropping it would starve the slot.

The relaxations matter as much as the constraints. A variety preference that
takes a plan down is worse than the repeat it was preventing, so each one is
pinned in both directions: it binds where it can, and it stands down where the
arithmetic says it cannot.
"""

import datetime as dt

import pandas as pd
import pytest
from ortools.sat.python import cp_model

from src.menu_rules.attribute_grouping_rule import AttributeGroupingRule


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


def _cell(model, di, base_slot, ingredients, tag=''):
    rows = [pd.Series({'item': f'{base_slot}{tag}_{di}_{i}', 'key_ingredient': k})
            for i, k in enumerate(ingredients)]
    xs = [model.NewBoolVar(f'x_{di}_{base_slot}{tag}_{i}')
          for i in range(len(ingredients))]
    model.Add(sum(xs) == 1)
    return _FakeCell(di, base_slot, rows, xs)


def _ctx(cells, n_days, declared=None):
    return {
        'cells': cells,
        'dates': [dt.date(2026, 3, 23) + dt.timedelta(days=i) for i in range(n_days)],
        'link_any_fn': _link_any,
        'extra_repeatable': declared or {},
    }


def _solve(model):
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5
    solver.parameters.num_search_workers = 1
    return solver, solver.Solve(model)


def _chosen(solver, cell):
    for var, row in zip(cell.x_vars, cell.cand_rows):
        if solver.Value(var):
            return row['key_ingredient']
    return None


class TestTheVegPlateDoesNotEcho:
    """`max_cells_per_day: 1` over veg_gravy + veg_dry."""

    def _rule(self):
        return AttributeGroupingRule({
            'name': 'veg_plate_distinct', 'type': 'attribute_grouping',
            'base_slot': ['veg_gravy', 'veg_dry'],
            'group_by': 'key_ingredient', 'max_cells_per_day': 1,
        })

    def test_a_shared_ingredient_is_forbidden_on_one_plate(self):
        # Both slots CAN take paneer; exactly one of them may.
        model = cp_model.CpModel()
        gravy = _cell(model, 0, 'veg_gravy', ['paneer', 'potato'])
        dry = _cell(model, 0, 'veg_dry', ['paneer', 'cabbage'])
        self._rule().apply(model, {}, None, _ctx([gravy, dry], 1))
        solver, status = _solve(model)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        assert _chosen(solver, gravy) != _chosen(solver, dry)

    def test_the_echo_is_genuinely_unsatisfiable_when_only_one_value_exists(self):
        # Both cells can ONLY be paneer: the rule is a real constraint, so this
        # is INFEASIBLE rather than silently ignored. The shipped config never
        # hits it — all 78 veg counters were measured as separable — and a test
        # that only proved the happy path would not show the rule binds at all.
        model = cp_model.CpModel()
        gravy = _cell(model, 0, 'veg_gravy', ['paneer'])
        dry = _cell(model, 0, 'veg_dry', ['paneer'])
        self._rule().apply(model, {}, None, _ctx([gravy, dry], 1))
        _, status = _solve(model)
        assert status == cp_model.INFEASIBLE

    def test_two_cells_of_one_slot_also_differ(self):
        # veg_dry running two dishes is the common shape; the constraint spans
        # cells, not slots, so the pair inside one slot is covered too.
        model = cp_model.CpModel()
        a = _cell(model, 0, 'veg_dry', ['paneer', 'potato'], tag='a')
        b = _cell(model, 0, 'veg_dry', ['paneer', 'cabbage'], tag='b')
        self._rule().apply(model, {}, None, _ctx([a, b], 1))
        solver, status = _solve(model)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        assert _chosen(solver, a) != _chosen(solver, b)

    def test_a_slot_outside_the_list_is_untouched(self):
        # dal is `dal` on every counter in the fleet; scoping is what keeps this
        # rule from being the plate-wide version that cannot be built.
        model = cp_model.CpModel()
        gravy = _cell(model, 0, 'veg_gravy', ['paneer'])
        dal = _cell(model, 0, 'dal', ['paneer'])
        self._rule().apply(model, {}, None, _ctx([gravy, dal], 1))
        _, status = _solve(model)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    def test_a_blank_ingredient_never_collides(self):
        # Two untagged dishes are not evidence of an echo. `require_value` is
        # how blanks are dealt with; this rule must not invent a collision.
        model = cp_model.CpModel()
        gravy = _cell(model, 0, 'veg_gravy', [''])
        dry = _cell(model, 0, 'veg_dry', [''])
        self._rule().apply(model, {}, None, _ctx([gravy, dry], 1))
        _, status = _solve(model)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)


class TestTheGapBetweenRepeats:
    def _rule(self, gap):
        return AttributeGroupingRule({
            'name': 'ki_gap', 'base_slot': 'veg_gravy',
            'group_by': 'key_ingredient', 'min_days_between': gap,
            'per_base_slot': True,
        })

    def test_three_clear_days_means_the_fourth_day_may_repeat(self):
        # paneer on day 0 blocks days 1-3 and is free again on day 4.
        model = cp_model.CpModel()
        cells = [_cell(model, di, 'veg_gravy',
                       ['paneer', 'potato', 'cabbage', 'carrot'])
                 for di in range(5)]
        model.Add(cells[0].x_vars[0] == 1)   # pin paneer on day 0
        self._rule(3).apply(model, {}, None, _ctx(cells, 5))
        solver, status = _solve(model)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        picked = [_chosen(solver, c) for c in cells]
        assert picked[0] == 'paneer'
        assert 'paneer' not in picked[1:4]

    def test_a_repeat_inside_the_window_is_infeasible(self):
        # The pool must be deep enough that the stand-down below does NOT fire,
        # or this would pass for the wrong reason — the rule relaxing, not the
        # rule binding.
        model = cp_model.CpModel()
        cells = [_cell(model, di, 'veg_gravy',
                       ['paneer', 'potato', 'cabbage', 'carrot', 'beans'])
                 for di in range(4)]
        model.Add(cells[0].x_vars[0] == 1)   # paneer on day 0
        model.Add(cells[2].x_vars[0] == 1)   # paneer again on day 2, inside the gap
        self._rule(3).apply(model, {}, None, _ctx(cells, 4))
        _, status = _solve(model)
        assert status == cp_model.INFEASIBLE

    def test_non_consecutive_is_still_exactly_a_one_day_gap(self):
        # Sixty shipped configs say `non_consecutive`; the refactor must not
        # have moved them by a day in either direction.
        r = AttributeGroupingRule({
            'name': 'x', 'base_slot': 'dal', 'group_by': 'item_color',
            'non_consecutive': True})
        assert r._gap == 1
        assert AttributeGroupingRule({
            'name': 'x', 'group_by': 'item_color',
            'min_days_between': 1})._gap == 1

    def test_the_gap_stands_down_rather_than_failing_a_thin_slot(self):
        # Two ingredients cannot fill a four-day window. The rule relaxes for
        # that slot instead of taking the plan down — nonveg_main's shape, where
        # six key ingredients meet a mandated daily chicken gravy.
        model = cp_model.CpModel()
        cells = [_cell(model, di, 'veg_gravy', ['paneer', 'potato'])
                 for di in range(5)]
        self._rule(3).apply(model, {}, None, _ctx(cells, 5))
        _, status = _solve(model)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    def test_a_declared_staple_is_exempt(self):
        # A rule has said this dish may recur; a variety cap that then forbids
        # it would be two rules disagreeing about one dish (note 19). The
        # declaration is a PARSED matcher tuple, which is the shape
        # `unique_items` actually reads — a raw selector dict is accepted by
        # the config and then blows up inside `_matches`.
        from src.menu_rules.selector_frequency_rule import SelectorFrequencyRule
        parse = SelectorFrequencyRule._parse_matcher
        model = cp_model.CpModel()
        cells = [_cell(model, di, 'veg_gravy',
                       ['paneer', 'potato', 'cabbage', 'carrot', 'beans'])
                 for di in range(4)]
        for c in cells:
            model.Add(c.x_vars[0] == 1)      # paneer every single day
        declared = {'veg_gravy': [(parse({'key_ingredient': 'paneer'}),
                                   parse(None))]}
        self._rule(3).apply(model, {}, None, _ctx(cells, 4, declared))
        _, status = _solve(model)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    def test_an_undeclared_dish_in_the_same_slot_still_binds(self):
        # The exemption must be scoped to the declared dish, not switch the
        # rule off for the slot it sits in.
        from src.menu_rules.selector_frequency_rule import SelectorFrequencyRule
        parse = SelectorFrequencyRule._parse_matcher
        model = cp_model.CpModel()
        cells = [_cell(model, di, 'veg_gravy',
                       ['paneer', 'potato', 'cabbage', 'carrot', 'beans'])
                 for di in range(4)]
        model.Add(cells[0].x_vars[1] == 1)   # potato on day 0
        model.Add(cells[2].x_vars[1] == 1)   # potato again inside the gap
        declared = {'veg_gravy': [(parse({'key_ingredient': 'paneer'}),
                                   parse(None))]}
        self._rule(3).apply(model, {}, None, _ctx(cells, 4, declared))
        _, status = _solve(model)
        assert status == cp_model.INFEASIBLE


class TestPerBaseSlotScoping:
    def test_each_slot_is_constrained_on_its_own(self):
        # Without per_base_slot the day's cells pool, so a gravy and a dry
        # sharing a value would collide across slots — the plate-wide reading
        # that cannot be built. With it, each slot answers for itself.
        model = cp_model.CpModel()
        cells = []
        for di in range(2):
            cells.append(_cell(model, di, 'veg_gravy', ['paneer'], tag='g'))
            cells.append(_cell(model, di, 'veg_dry', ['paneer'], tag='d'))
        rule = AttributeGroupingRule({
            'name': 'x', 'group_by': 'key_ingredient',
            'min_days_between': 1, 'per_base_slot': True})
        rule.apply(model, {}, None, _ctx(cells, 2))
        _, status = _solve(model)
        # Each slot is down to one value on both days, so the gap relaxes per
        # slot; what matters is that the two slots were never pooled together.
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    def test_scopes_are_ordered_deterministically(self):
        # Variable names are derived from the scope's position in a SORTED
        # list, never from hash(name) — string hashing is salted per process,
        # so a hash would give the same model different names on each run.
        rule = AttributeGroupingRule({
            'name': 'x', 'group_by': 'key_ingredient',
            'min_days_between': 1, 'per_base_slot': True})
        model = cp_model.CpModel()
        cells = [_cell(model, 0, s, ['paneer']) for s in ('veg_gravy', 'dal', 'rice')]
        assert [n for n, _ in rule._scopes(cells)] == ['dal', 'rice', 'veg_gravy']


class TestRequireValue:
    def _rule(self):
        return AttributeGroupingRule({
            'name': 'x', 'base_slot': ['veg_gravy'],
            'group_by': 'key_ingredient', 'max_cells_per_day': 1,
            'require_value': True})

    def _pool(self, ingredients):
        return pd.DataFrame([
            {'item': f'd{i}', 'key_ingredient': k, 'course_type': 'veg_gravy'}
            for i, k in enumerate(ingredients)])

    def _ctx(self, days=1, per_day=1):
        class _Cfg:
            slot_counts = {'veg_gravy': per_day}
        _Cfg.days = days
        return {'cfg': _Cfg, 'extra_repeatable': {}}

    def test_blank_rows_leave_the_pool(self):
        pool = self._pool(['paneer', None, 'potato', '', 'carrot'])
        out = self._rule().pre_filter_pool(
            pool, dt.date(2026, 3, 23), 'veg_gravy', 'mix', self._ctx(days=1))
        assert sorted(out['key_ingredient']) == ['carrot', 'paneer', 'potato']

    def test_a_nan_is_recognised_as_blank(self):
        # The defect this whole feature had to route around: `.astype(str)` does
        # not stringify NaN under pandas' str dtype, so a NaN read as a value.
        pool = pd.DataFrame([
            {'item': 'a', 'key_ingredient': 'paneer'},
            {'item': 'b', 'key_ingredient': float('nan')},
        ])
        out = self._rule().pre_filter_pool(
            pool, dt.date(2026, 3, 23), 'veg_gravy', 'mix', self._ctx(days=1))
        assert list(out['item']) == ['a']

    def test_the_drop_stands_down_rather_than_starving_a_slot(self):
        # Booking.com's nonveg_soup and infused_water are 100% blank, so the
        # filter would empty them outright. Every candidate is kept instead.
        pool = self._pool([None, None, ''])
        out = self._rule().pre_filter_pool(
            pool, dt.date(2026, 3, 23), 'veg_gravy', 'mix', self._ctx(days=5))
        assert len(out) == 3

    def test_the_drop_stands_down_when_too_few_survive_for_the_horizon(self):
        # Corning Chakan's starter goes 16 -> 3 against a five-day plan. Three
        # dishes cannot fill five days under unique_items, so the rule gives way.
        pool = self._pool(['paneer', 'potato', 'carrot', None, None, None])
        out = self._rule().pre_filter_pool(
            pool, dt.date(2026, 3, 23), 'veg_gravy', 'mix', self._ctx(days=5))
        assert len(out) == 6

    def test_a_slot_outside_the_list_is_untouched(self):
        pool = self._pool(['paneer', None])
        out = self._rule().pre_filter_pool(
            pool, dt.date(2026, 3, 23), 'starter', 'mix', self._ctx(days=1))
        assert len(out) == 2

    def test_without_require_value_nothing_is_dropped(self):
        r = AttributeGroupingRule({
            'name': 'x', 'base_slot': ['veg_gravy'],
            'group_by': 'key_ingredient', 'max_cells_per_day': 1})
        pool = self._pool(['paneer', None])
        out = r.pre_filter_pool(pool, dt.date(2026, 3, 23), 'veg_gravy', 'mix',
                                self._ctx(days=1))
        assert len(out) == 2


class TestTheSoftPlateEcho:
    """`soft_preference.avoid_attribute_repeat` at `scope: day` / `week`.

    Soft, so these assert PREFERENCE, not feasibility. The hard rule above
    covers the veg plate; this covers everything else, where a slot's identity
    (chicken, dal, wheat) must be able to outbid the preference.
    """

    def _rule(self, scope, weight=1000):
        from src.menu_rules.soft_preference_rule import SoftPreferenceRule
        return SoftPreferenceRule({
            'name': 'plate_echo', 'mode': 'avoid_attribute_repeat',
            'group_by': 'key_ingredient', 'scope': scope, 'weight': weight})

    def _maximise(self, model, terms):
        model.Maximize(sum(terms))
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 5
        solver.parameters.num_search_workers = 1
        return solver, solver.Solve(model)

    def test_day_scope_separates_two_cells_of_one_plate(self):
        model = cp_model.CpModel()
        gravy = _cell(model, 0, 'veg_gravy', ['paneer', 'potato'])
        dry = _cell(model, 0, 'veg_dry', ['paneer', 'cabbage'])
        ctx = _ctx([gravy, dry], 1)
        terms = self._rule('day').get_objective_terms(model, ctx)
        solver, status = self._maximise(model, terms)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        assert _chosen(solver, gravy) != _chosen(solver, dry)

    def test_horizon_scope_cannot_see_a_same_day_echo(self):
        # Not a defect — it is why `scope: day` had to be added. The default
        # collapses a value to one bool per DAY, so two cells sharing it on one
        # plate are invisible to it. Pinned so nobody "fixes" the default and
        # silently changes sixty shipped configs.
        model = cp_model.CpModel()
        gravy = _cell(model, 0, 'veg_gravy', ['paneer', 'potato'])
        dry = _cell(model, 0, 'veg_dry', ['paneer', 'cabbage'])
        ctx = _ctx([gravy, dry], 1)
        terms = self._rule('horizon').get_objective_terms(model, ctx)
        assert not terms

    def test_week_scope_buckets_by_iso_week(self):
        # Two ISO weeks: one paneer in each is NOT a repeat under `week`, while
        # `horizon` would count it as one.
        from src.menu_rules.soft_preference_rule import SoftPreferenceRule
        model = cp_model.CpModel()
        # 2026-03-23 is a Monday; d_idx 0..6 spans Mon-Sun, d_idx 7 is next week.
        cells = [_cell(model, di, 'veg_gravy', ['paneer', 'potato'])
                 for di in (0, 7)]
        ctx = {
            'cells': cells,
            'dates': [dt.date(2026, 3, 23) + dt.timedelta(days=i) for i in range(8)],
            'link_any_fn': _link_any,
        }
        cells[0].d_idx, cells[1].d_idx = 0, 7
        weekly = SoftPreferenceRule({
            'name': 'w', 'mode': 'avoid_attribute_repeat',
            'group_by': 'key_ingredient', 'scope': 'week', 'weight': 1000})
        assert not weekly.get_objective_terms(model, ctx)
        horizon = SoftPreferenceRule({
            'name': 'h', 'mode': 'avoid_attribute_repeat',
            'group_by': 'key_ingredient', 'weight': 1000})
        assert horizon.get_objective_terms(model, ctx)

    def test_the_penalty_can_be_outbid(self):
        # A slot whose ingredient IS its identity must still be servable. Here
        # a bonus larger than the echo penalty buys the repeat.
        model = cp_model.CpModel()
        a = _cell(model, 0, 'nonveg_main', ['chicken', 'egg'], tag='a')
        b = _cell(model, 0, 'nonveg_main', ['chicken'], tag='b')
        ctx = _ctx([a, b], 1)
        terms = self._rule('day', weight=10).get_objective_terms(model, ctx)
        terms = list(terms) + [a.x_vars[0] * 100_000]   # something wants chicken
        solver, status = self._maximise(model, terms)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        assert _chosen(solver, a) == 'chicken' and _chosen(solver, b) == 'chicken'

    def test_an_unknown_scope_is_rejected(self):
        from src.menu_rules.soft_preference_rule import SoftPreferenceRule
        r = SoftPreferenceRule({
            'name': 'x', 'mode': 'avoid_attribute_repeat',
            'group_by': 'key_ingredient', 'scope': 'fortnight'})
        assert not r.validate_config()
        assert any('scope' in e for e in r.validation_errors())

    def test_the_default_scope_is_horizon(self):
        from src.menu_rules.soft_preference_rule import SoftPreferenceRule
        assert SoftPreferenceRule({
            'name': 'x', 'mode': 'avoid_attribute_repeat',
            'group_by': 'key_ingredient'}).scope == 'horizon'


class TestConfigValidation:
    def test_max_cells_per_day_stands_alone(self):
        r = AttributeGroupingRule({
            'name': 'x', 'base_slot': ['veg_gravy', 'veg_dry'],
            'group_by': 'key_ingredient', 'max_cells_per_day': 1})
        assert r.validate_config(), r.validation_errors()

    def test_zero_cells_per_day_is_rejected(self):
        r = AttributeGroupingRule({
            'name': 'x', 'group_by': 'key_ingredient', 'max_cells_per_day': 0})
        assert not r.validate_config()
        assert any('max_cells_per_day' in e for e in r.validation_errors())

    def test_zero_gap_is_rejected(self):
        r = AttributeGroupingRule({
            'name': 'x', 'group_by': 'key_ingredient', 'min_days_between': 0})
        assert not r.validate_config()
        assert any('min_days_between' in e for e in r.validation_errors())

    @pytest.mark.parametrize('bs,expected', [
        ('dal', {'dal'}),
        (['veg_gravy', 'veg_dry'], {'veg_gravy', 'veg_dry'}),
        (None, None),
    ])
    def test_base_slot_accepts_a_name_or_a_list(self, bs, expected):
        r = AttributeGroupingRule({
            'name': 'x', 'base_slot': bs, 'group_by': 'key_ingredient',
            'max_cells_per_day': 1})
        assert r.base_slots == expected
        # The string form survives for diagnose(), which is single-slot.
        assert r.base_slot == (bs if isinstance(bs, str) else None)
