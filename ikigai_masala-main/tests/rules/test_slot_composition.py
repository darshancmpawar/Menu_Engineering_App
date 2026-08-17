"""Tests for the slot_composition rule + the 2-nonveg theme-filter union.

The rule composes a slot family per day, switching on the day's theme, and must
never force an INFEASIBLE model (auto-relax on a thin pool).
"""

import pandas as pd
import pytest
from ortools.sat.python import cp_model

from src.menu_rules.slot_composition_rule import SlotCompositionRule
from src.menu_rules.theme_rules import ThemeSlotFilterRule


# --- candidate rows (one dict per selectable item) ------------------------
DRY = {'is_nonveg_dry': 1}
NORTH = {'is_north_chicken_gravy': 1}
SOUTH = {'is_south_chicken_gravy': 1}
CHINESE = {'cuisine_family': 'chinese'}
BIRYANI = {'is_nonveg_biryani': 1}
NORTH_VD = {'cuisine_family': 'north_indian'}
SOUTH_VD = {'cuisine_family': 'south_indian'}


class _Cell:
    def __init__(self, d_idx, base_slot, x_vars, cand_rows):
        self.d_idx = d_idx
        self.base_slot = base_slot
        self.x_vars = x_vars
        self.cand_rows = cand_rows


def _solve(rule, day_type, n_cells, candidates, base_slot='nonveg_main',
           pin=None):
    """Build ``n_cells`` cells (each picks exactly one of ``candidates``), apply
    the rule for a single day of ``day_type``, solve, and return (status_name,
    [picked candidate index per cell]). ``pin`` optionally forces cell 0 to a
    given candidate index."""
    m = cp_model.CpModel()
    cells = []
    for ci in range(n_cells):
        xs = [m.NewBoolVar(f'c{ci}_{i}') for i in range(len(candidates))]
        m.Add(sum(xs) == 1)
        cells.append(_Cell(0, base_slot, xs, list(candidates)))
    if pin is not None:
        m.Add(cells[0].x_vars[pin] == 1)
    rule.apply(m, {}, None,
               {'cells': cells, 'dates': [None], 'day_types': [day_type]})
    solver = cp_model.CpSolver()
    status = solver.Solve(m)
    picks = []
    for c in cells:
        idx = [i for i, v in enumerate(c.x_vars) if solver.Value(v)]
        picks.append(idx[0] if idx else None)
    return solver.StatusName(status), picks


def _nonveg_rule():
    return SlotCompositionRule({
        'name': 'nonveg_main_daily_pair', 'type': 'slot_composition',
        'base_slot': 'nonveg_main', 'requires_slot_count': 2,
        'components': [
            {'selector': {'flag': 'is_nonveg_dry'}, 'count': 1},
            {'selector': {'any_flag': ['is_north_chicken_gravy',
                                       'is_south_chicken_gravy']}, 'count': 1},
        ],
        'components_by_theme': {
            'chinese': [
                {'selector': {'cuisine_family': 'chinese'}, 'count': 1},
                {'selector': {'any_flag': ['is_north_chicken_gravy',
                                           'is_south_chicken_gravy']}, 'count': 1},
            ],
            'biryani': [
                {'selector': {'flag': 'is_nonveg_biryani'}, 'count': 1},
                {'selector': {'any_flag': ['is_north_chicken_gravy',
                                           'is_south_chicken_gravy']}, 'count': 1},
            ],
        },
    })


class TestNonvegComposition:
    CANDS = [DRY, NORTH, SOUTH, CHINESE, BIRYANI]
    LABELS = ['dry', 'north', 'south', 'chinese', 'biryani']

    def _roles(self, picks):
        return sorted(self.LABELS[p] for p in picks)

    def test_chicken_day_is_one_dry_one_gravy(self):
        status, picks = _solve(_nonveg_rule(), 'mix', 2, self.CANDS)
        assert status in ('OPTIMAL', 'FEASIBLE')
        roles = self._roles(picks)
        assert 'dry' in roles
        assert roles.count('north') + roles.count('south') == 1
        assert 'biryani' not in roles and 'chinese' not in roles

    def test_chinese_day_is_one_chinese_one_gravy(self):
        status, picks = _solve(_nonveg_rule(), 'chinese', 2, self.CANDS)
        assert status in ('OPTIMAL', 'FEASIBLE')
        roles = self._roles(picks)
        assert 'chinese' in roles
        assert roles.count('north') + roles.count('south') == 1
        assert 'dry' not in roles and 'biryani' not in roles

    def test_biryani_day_is_one_biryani_one_gravy(self):
        status, picks = _solve(_nonveg_rule(), 'biryani', 2, self.CANDS)
        assert status in ('OPTIMAL', 'FEASIBLE')
        roles = self._roles(picks)
        assert 'biryani' in roles
        assert roles.count('north') + roles.count('south') == 1

    def test_self_gate_skips_single_slot_counter(self):
        # requires_slot_count=2 but only 1 cell: the rule must add no constraint,
        # so pinning the single cell to a biryani on a mix day stays feasible.
        status, picks = _solve(_nonveg_rule(), 'mix', 1, self.CANDS, pin=4)
        assert status in ('OPTIMAL', 'FEASIBLE')
        assert picks == [4]  # biryani, unconstrained

    def test_auto_relax_when_no_dry_available(self):
        # Pool has only gravies (no dry). `==` semantics would be INFEASIBLE
        # (both cells must be gravy but "exactly one gravy" is impossible);
        # `>=` relaxes to two gravies.
        status, picks = _solve(_nonveg_rule(), 'mix', 2, [NORTH, SOUTH])
        assert status in ('OPTIMAL', 'FEASIBLE')  # never INFEASIBLE
        assert all(p in (0, 1) for p in picks)

    def test_missing_theme_falls_back_to_default_components(self):
        # 'north' theme has no override → uses default (dry + gravy).
        status, picks = _solve(_nonveg_rule(), 'north', 2, self.CANDS)
        assert status in ('OPTIMAL', 'FEASIBLE')
        roles = self._roles(picks)
        assert 'dry' in roles and roles.count('north') + roles.count('south') == 1


class TestVegDryComposition:
    def test_one_north_one_south(self):
        rule = SlotCompositionRule({
            'name': 'veg_dry_north_south_pair', 'type': 'slot_composition',
            'base_slot': 'veg_dry', 'requires_slot_count': 2,
            'components': [
                {'selector': {'cuisine_family': 'north_indian'}, 'count': 1},
                {'selector': {'cuisine_family': 'south_indian'}, 'count': 1},
            ],
        })
        cands = [NORTH_VD, SOUTH_VD]
        status, picks = _solve(rule, 'mix', 2, cands, base_slot='veg_dry')
        assert status in ('OPTIMAL', 'FEASIBLE')
        assert sorted(picks) == [0, 1]  # one north + one south


class TestConfigValidation:
    def test_needs_base_slot_and_components(self):
        assert SlotCompositionRule({'name': 'x', 'type': 'slot_composition'}) \
            .validate_config() is False

    def test_bad_component_is_flagged(self):
        r = SlotCompositionRule({
            'name': 'x', 'type': 'slot_composition', 'base_slot': 'nonveg_main',
            'components': [{'selector': {'flag': 'is_x'}, 'count': 0}],  # count<1
        })
        assert r.validate_config() is False


class TestThemeFilterNonvegUnion:
    """On a 2-nonveg counter the theme filter must keep north/south chicken
    gravies on chinese/biryani/cuisine days; a 1-nonveg counter is unchanged."""

    class _Cfg:
        def __init__(self, n):
            self.slot_counts = {'nonveg_main': n}
            self.cuisine_col = 'cuisine_family'
            self.cuisine_south_value = 'south_indian'
            self.cuisine_north_value = 'north_indian'

    @pytest.fixture(scope='class')
    def nonveg_pool(self, sample_data_path):
        df = pd.read_excel(sample_data_path)
        return df[df['course_type'] == 'nonveg_main'].copy()

    @staticmethod
    def _regional_count(pool):
        n = (pool.get('is_north_chicken_gravy', 0) == 1)
        s = (pool.get('is_south_chicken_gravy', 0) == 1)
        return int((n | s).sum())

    @pytest.mark.parametrize('day', ['chinese', 'biryani'])
    def test_two_nonveg_retains_regional_gravy(self, nonveg_pool, day):
        rule = ThemeSlotFilterRule({'name': 't', 'type': 'theme_slot_filter'})
        one = rule.pre_filter_pool(nonveg_pool.copy(), None, 'nonveg_main', day,
                                   {'cfg': self._Cfg(1)})
        two = rule.pre_filter_pool(nonveg_pool.copy(), None, 'nonveg_main', day,
                                   {'cfg': self._Cfg(2)})
        assert self._regional_count(one) == 0        # single-slot: narrowed away
        assert self._regional_count(two) > 0         # two-slot: kept
        assert len(two) > len(one)

    def test_veg_dry_untouched_by_nonveg_union(self, sample_data_path):
        # The union is nonveg_main-only; veg_dry must be unaffected.
        df = pd.read_excel(sample_data_path)
        vd = df[df['course_type'] == 'veg_dry'].copy()
        rule = ThemeSlotFilterRule({'name': 't', 'type': 'theme_slot_filter'})
        a = rule.pre_filter_pool(vd.copy(), None, 'veg_dry', 'chinese',
                                 {'cfg': self._Cfg(1)})
        b = rule.pre_filter_pool(vd.copy(), None, 'veg_dry', 'chinese',
                                 {'cfg': self._Cfg(2)})
        assert len(a) == len(b)
