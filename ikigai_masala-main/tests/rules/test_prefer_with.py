"""prefer_with: "if A is on the plate, B should be too" (soft pairing).

The properties that matter, in order: it never changes feasibility, it pays for
the pairing once (not per pair), it gives no reason to serve the trigger, it is
skipped where the target cannot exist, and its weight is not lost under the
freshness bonus and random tie-break.
"""
import datetime as dt

import pandas as pd
import pytest
from ortools.sat.python import cp_model

from src.constants import OBJECTIVE_TIER_WEIGHTS
from src.menu_rules.base_menu_rule import DiagnoseContext
from src.menu_rules.soft_preference_rule import SoftPreferenceRule
from src.solver.menu_solver import MAX_FRESHNESS_BONUS

from tests.rules.test_soft_preference import (
    _cell, _ctx, _maximize,
)

A = {'flag': 'is_a'}
B = {'flag': 'is_b'}


def _rule(**kw):
    cfg = {'name': 'a_with_b', 'type': 'soft_preference', 'mode': 'prefer_with',
           'selector_a': A, 'base_slot_a': 'rice',
           'selector_b': B, 'base_slot_b': 'gravy', 'priority': 'low'}
    cfg.update(kw)
    return SoftPreferenceRule(cfg)


def _solve(rule, cells, n_days=1, extra=None, ctx_extra=None):
    m = cp_model.CpModel()
    built = cells(m)
    ctx = _ctx(built, n_days)
    ctx.update(ctx_extra or {})
    terms = rule.get_objective_terms(m, ctx)
    if extra:
        extra(m, built)
    solver, status = _maximize(m, terms)
    return solver, status, built, terms


class TestConfig:
    def test_valid(self):
        assert _rule().validate_config()

    def test_needs_both_selectors_and_slots(self):
        assert not _rule(selector_b=None).validate_config()
        assert not _rule(base_slot_a=None).validate_config()

    def test_typo_selector_key_is_rejected_not_inert(self):
        # note 9: a selector that parses to nothing must fail at the write.
        assert not _rule(selector_a={'flagg': 'is_a'}).validate_config()

    def test_high_priority_refused(self):
        assert not _rule(priority='high').validate_config()
        assert not _rule(priority='theme').validate_config()
        assert _rule(priority='medium').validate_config()


class TestBehaviour:
    def test_prefers_the_target_when_trigger_is_forced(self):
        def cells(m):
            rice = _cell(m, 0, 'rice', [{'is_a': 1}])           # trigger forced
            gravy = _cell(m, 0, 'gravy', [{'is_b': 0}, {'is_b': 1}])
            return [rice, gravy]
        solver, st, built, terms = _solve(_rule(), cells)
        assert st == cp_model.OPTIMAL
        gravy = built[1]
        assert solver.Value(gravy.x_vars[1]) == 1

    def test_no_reason_to_serve_the_trigger(self):
        # Implication, not conjunction: the best objective is 0, never > 0.
        def cells(m):
            rice = _cell(m, 0, 'rice', [{'is_a': 1}, {'is_a': 0}])
            gravy = _cell(m, 0, 'gravy', [{'is_b': 1}])
            return [rice, gravy]
        solver, st, _b, _t = _solve(_rule(), cells)
        assert solver.ObjectiveValue() <= 0

    def test_trigger_absent_means_no_penalty(self):
        def cells(m):
            rice = _cell(m, 0, 'rice', [{'is_a': 0}])
            gravy = _cell(m, 0, 'gravy', [{'is_b': 0}, {'is_b': 1}])
            return [rice, gravy]
        solver, st, _b, _t = _solve(_rule(), cells)
        assert solver.ObjectiveValue() == 0

    def test_paid_once_not_per_target(self):
        # Two target cells both satisfied: the reward is not doubled.
        def cells(m):
            rice = _cell(m, 0, 'rice', [{'is_a': 1}])
            g1 = _cell(m, 0, 'gravy', [{'is_b': 1}])
            g2 = _cell(m, 0, 'gravy', [{'is_b': 1}])
            return [rice, g1, g2]
        solver, _st, _b, _t = _solve(_rule(), cells)
        assert solver.ObjectiveValue() == 0

    def test_never_changes_feasibility(self):
        # B candidate exists but a hard rule forbids every one of them.
        def cells(m):
            rice = _cell(m, 0, 'rice', [{'is_a': 1}])
            gravy = _cell(m, 0, 'gravy', [{'is_b': 1}, {'is_b': 0}])
            return [rice, gravy]

        def ban_b(m, built):
            m.Add(built[1].x_vars[0] == 0)
        solver, st, built, _t = _solve(_rule(), cells, extra=ban_b)
        assert st == cp_model.OPTIMAL
        assert solver.Value(built[1].x_vars[1]) == 1
        assert solver.ObjectiveValue() == -OBJECTIVE_TIER_WEIGHTS['low']

    def test_skipped_when_target_has_no_candidate(self):
        def cells(m):
            rice = _cell(m, 0, 'rice', [{'is_a': 1}])
            gravy = _cell(m, 0, 'gravy', [{'is_b': 0}])
            return [rice, gravy]
        m = cp_model.CpModel()
        terms = _rule().get_objective_terms(m, _ctx(cells(m), 1))
        assert terms == []            # a constant the solver cannot act on

    def test_day_types_scope(self):
        def cells(m):
            return [
                _cell(m, 0, 'rice', [{'is_a': 1}]),
                _cell(m, 0, 'gravy', [{'is_b': 0}, {'is_b': 1}]),
                _cell(m, 1, 'rice', [{'is_a': 1}]),
                _cell(m, 1, 'gravy', [{'is_b': 0}, {'is_b': 1}]),
            ]
        rule = _rule(day_types=['biryani'])
        m = cp_model.CpModel()
        built = cells(m)
        ctx = _ctx(built, 2)
        ctx['day_types'] = ['mix', 'biryani']
        terms = rule.get_objective_terms(m, ctx)
        solver, _st = _maximize(m, terms)
        # Day 1 (biryani) pairs; day 0 (mix) is unscored so nothing pulls it.
        assert solver.Value(built[3].x_vars[1]) == 1


class TestWeight:
    def test_low_tier_outranks_freshness_and_tiebreak(self):
        # The 30-vs-10 failure mode: a pairing worth less than the noise.
        noise = MAX_FRESHNESS_BONUS + 1000
        assert _rule(priority='low').weight > 10 * noise
        assert _rule(priority='medium').weight > _rule(priority='low').weight


class TestDiagnose:
    def _ctx(self, pools):
        return DiagnoseContext(
            pools=pools, dates=[dt.date(2026, 3, 23)], day_types={}, cfg=None,
            df=pd.DataFrame(), banned_by_date={}, ricebread_ban_day={},
            skip_cells=set(), client_cfg=None)

    def test_warns_when_target_matches_nothing(self):
        pools = {'rice': pd.DataFrame([{'item': 'x', 'is_a': 1}]),
                 'gravy': pd.DataFrame([{'item': 'y', 'is_b': 0}])}
        out = _rule().diagnose(self._ctx(pools))
        assert len(out) == 1 and out[0].severity.value == 'warning'

    def test_quiet_when_target_exists(self):
        pools = {'rice': pd.DataFrame([{'item': 'x', 'is_a': 1}]),
                 'gravy': pd.DataFrame([{'item': 'y', 'is_b': 1}])}
        assert _rule().diagnose(self._ctx(pools)) == []

    def test_idle_when_no_trigger_in_pool(self):
        pools = {'rice': pd.DataFrame([{'item': 'x', 'is_a': 0}]),
                 'gravy': pd.DataFrame([{'item': 'y', 'is_b': 0}])}
        assert _rule().diagnose(self._ctx(pools)) == []


class TestMatcherColumnsStaysInStepWithMatches:
    """`matcher_columns` says which columns a selector reads, so `diagnose()`
    can project a 143-column pool down to two before walking it (505 ms -> 48 ms
    for the six catalogue rules over the real Bangalore pools).

    The projection is only safe while the two agree. A selector kind that reads
    a column `matcher_columns` forgets would make the projected frame answer
    differently from the full one — a wrong count that looks like a right one,
    which is the whole failure mode `diagnose()` exists to prevent.
    """

    SELECTORS = [
        {'flag': 'is_aloo_gravy'},
        {'any_flag': ['is_biryani_item', 'is_nonveg_biryani']},
        {'sub_category': 'tandoor'},
        {'course_type': 'sambar'},
        {'name_contains': ['salan']},
        {'any_of': [{'flag': 'is_paneer_gravy'},
                    {'sub_category': 'creamy_dal_(makhni/dhaba)'}]},
        {'all_of': [{'flag': 'is_raita'}, {'course_type': 'curd_side'}]},
        {'none_of': [{'flag': 'is_raita'}]},
        {'primary_protein': 'paneer'},
        {'key_ingredient': 'mushroom'},
    ]

    @pytest.mark.parametrize('sel', SELECTORS)
    def test_a_projected_frame_counts_the_same_as_the_whole_one(self, sel):
        from src.menu_rules.selector_frequency_rule import SelectorFrequencyRule as SF
        rows = [
            {'item': 'veg_salan', 'is_aloo_gravy': 0, 'is_biryani_item': 1,
             'is_nonveg_biryani': 0, 'sub_category': 'tandoor',
             'course_type': 'sambar', 'is_paneer_gravy': 1, 'is_raita': 0,
             'primary_protein': 'paneer', 'key_ingredient': 'mushroom',
             'spice_level': 3, 'richness_score': 4, 'texture': 'saucy'},
            {'item': 'aloo_gravy', 'is_aloo_gravy': 1, 'is_biryani_item': 0,
             'is_nonveg_biryani': 0, 'sub_category': 'creamy_dal_(makhni/dhaba)',
             'course_type': 'veg_gravy', 'is_paneer_gravy': 0, 'is_raita': 1,
             'primary_protein': 'soy', 'key_ingredient': 'potato',
             'spice_level': 1, 'richness_score': 2, 'texture': 'dry'},
        ]
        frame = pd.DataFrame(rows)
        m = SF._parse_matcher(sel)
        assert m is not None, sel
        cols = SF.matcher_columns(m)
        keep = [c for c in cols if c in frame.columns]
        full = sum(1 for _i, r in frame.iterrows() if SF._matches(r, m))
        proj = sum(1 for r in (frame[keep] if keep else frame).to_dict('records')
                   if SF._matches(r, m))
        assert full == proj, (sel, sorted(cols), full, proj)

    def test_every_selector_kind_reports_at_least_one_column(self):
        """A kind that reports nothing projects to an empty frame, where every
        `row.get` returns the default and the count silently goes to zero."""
        from src.menu_rules.selector_frequency_rule import SelectorFrequencyRule as SF
        for sel in self.SELECTORS:
            cols = SF.matcher_columns(SF._parse_matcher(sel))
            assert cols, f'{sel} reports no columns'
