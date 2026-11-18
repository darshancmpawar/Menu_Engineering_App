"""`pairing`: one row follows another's dish that day (Rippling breakfast, 18 Nov).

Idli comes with a chutney and a sambar; poori with chole and nothing else, so
the second accompaniment is blank; a main the table has no pair for is not
served."""
from __future__ import annotations

import pytest
from ortools.sat.python import cp_model

from src.menu_rules.pairing_rule import PairingRule

RULE = PairingRule({
    'name': 'p', 'type': 'pairing', 'meals': ['breakfast'],
    'when_slot': 'breakfast_main', 'then_slot': 'accompaniment',
    'pairs': [
        {'when': {'name_contains': 'poori'}, 'then': [{'name_contains': 'chole'}, None]},
        {'when': {'sub_category': 'idly'}, 'then': [{'sub_category': 'chutney'}, {'sub_category': 'sambar'}]},
    ]})
MAINS = [{'item': 'plain_idly', 'sub_category': 'idly'}, {'item': 'masala_poori', 'sub_category': 'poori_bhature'},
         {'item': 'medu_vada', 'sub_category': 'vada'}]
SIDES = [{'item': 'coconut_chutney', 'sub_category': 'chutney'}, {'item': 'sambar', 'sub_category': 'sambar'},
         {'item': 'chole_masala', 'sub_category': 'breakfast_curry_gravy'}]


class _Cell:
    def __init__(self, model, slot_id, rows):
        self.d_idx, self.slot_id, self.base_slot = 0, slot_id, slot_id.split('__')[0]
        self.cand_rows = rows
        self.x_vars = [model.NewBoolVar(f'{slot_id}_{i}') for i in range(len(rows))]
        optional = slot_id in RULE.optional_slot_ids()
        model.Add(sum(self.x_vars) <= 1) if optional else model.Add(sum(self.x_vars) == 1)


def _solve(main):
    m = cp_model.CpModel()
    cells = [_Cell(m, 'breakfast_main', MAINS), _Cell(m, 'accompaniment__1', SIDES),
             _Cell(m, 'accompaniment__2', SIDES)]
    RULE.apply(m, {}, None, {'cells': cells})
    m.Add(cells[0].x_vars[[r['item'] for r in MAINS].index(main)] == 1)
    s = cp_model.CpSolver()
    if s.Solve(m) not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    return [next((r['item'] for v, r in zip(c.x_vars, c.cand_rows) if s.Value(v)), None) for c in cells[1:]]


def test_only_the_second_cell_may_be_blank():
    assert RULE.validate_config() and RULE.optional_slot_ids() == {'accompaniment__2'}


@pytest.mark.parametrize('main, sides', [('plain_idly', ['coconut_chutney', 'sambar']),
                                         ('masala_poori', ['chole_masala', None])])
def test_the_accompaniments_follow_the_main(main, sides):
    assert _solve(main) == sides


def test_a_main_with_no_pair_is_not_served():
    assert _solve('medu_vada') is None


def test_a_selector_that_does_not_parse_is_refused_not_read_as_blank():
    bad = PairingRule({'name': 'b', 'type': 'pairing', 'when_slot': 'a', 'then_slot': 'b',
                       'pairs': [{'when': {'sub_category': 'idly'}, 'then': [{'nonsense': 1}]}]})
    assert not bad.validate_config()


def _rule(then_slot, meals, then2):
    return PairingRule({'name': 'r', 'type': 'pairing', 'meals': meals, 'when_slot': 'breakfast_main',
                        'then_slot': then_slot,
                        'pairs': [{'when': {'sub_category': 'idly'}, 'then': [{'sub_category': 'chutney'}, then2]}]})


@pytest.mark.parametrize('then_slot, meals', [('bread', ['breakfast']), ('accompaniment', None),
                                              ('accompaniment', ['breakfast', 'lunch']), ('accompaniment', ['lunch'])])
def test_blank_only_in_breakfast_accompaniments(then_slot, meals):
    """Owner, 18 Nov: a cell may be blank only in breakfast's Accompaniments row."""
    r = _rule(then_slot, meals, None)
    assert not r.validate_config() and r.optional_slot_ids() == set()


def test_a_pairing_with_no_blank_works_on_any_row():
    assert _rule('bread', None, {'sub_category': 'sambar'}).validate_config()
