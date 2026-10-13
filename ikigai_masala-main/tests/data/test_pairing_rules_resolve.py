"""Every shipped `prefer_with` rule resolves against the city it ships to.

Note 9, aimed at the pairing layer: a selector that matches nothing loads
cleanly, reports itself satisfied and constrains nothing, and the menu looks
fine the whole time. A pairing is especially exposed to it because the rule is
SOFT — there is no INFEASIBLE to notice, no relaxation to stamp, and a city
whose workbook simply lacks the target dish produces exactly the plans it
produced before.

Reads the city rulesets and the five workbooks, and nothing else: no solver, no
database, no CP-SAT. The same shape as `test_dataset_guards.py`, and fast enough
to run on every commit.

What it does NOT assert is a minimum DEPTH. The work order proposes a floor of
five target rows so the item cooldown cannot starve a pair, and that floor is a
judgement about variety rather than about correctness — a pair with four targets
is enforceable, just repetitive. It is applied when a rule is enabled for a
city, and recorded in that rule's `_comment`, rather than asserted here where it
would read as a law.
"""

from __future__ import annotations

import pytest

from src.menu_rules.menu_rule_loader import MenuRuleLoader
from src.menu_rules.selector_frequency_rule import SelectorFrequencyRule
from src.ontology.repository import repository

CITIES = ['Bangalore', 'Hyderabad', 'Chennai', 'Pune', 'NCR']


def _prefer_with_rules(city):
    return [r for r in MenuRuleLoader().load_for_city(city)
            if getattr(r, 'mode', '') == 'prefer_with']


def _count(pools, slots, matcher):
    """Matching rows across *slots*, projected to the matcher's own columns."""
    cols = SelectorFrequencyRule.matcher_columns(matcher)
    n = 0
    for slot in sorted(slots or ()):
        pool = pools.get(slot)
        if pool is None or not len(pool):
            continue
        keep = [c for c in cols if c in pool.columns]
        n += sum(1 for r in (pool[keep] if keep else pool).to_dict('records')
                 if SelectorFrequencyRule._matches(r, matcher))
    return n


@pytest.mark.parametrize('city', CITIES)
def test_every_pairing_rule_resolves_in_its_city(city):
    _df, pools = repository.menu_data(city)
    for rule in _prefer_with_rules(city):
        n_a = _count(pools, rule.base_slot_a, rule._sel_a)
        n_b = _count(pools, rule.base_slot_b, rule._sel_b)
        assert n_a, (
            f'{city}/{rule.name}: the TRIGGER selector matches no row in '
            f'{sorted(rule.base_slot_a)}. The rule can never fire here — drop '
            f'it from this city rather than ship a rule that reads as enforced '
            f'(note 9).')
        assert n_b, (
            f'{city}/{rule.name}: the TARGET selector matches no row in '
            f'{sorted(rule.base_slot_b)}, so the pairing can never be honoured '
            f'and every trigger day pays the penalty for nothing.')


@pytest.mark.parametrize('city', CITIES)
def test_every_pairing_rule_names_slots_the_city_has(city):
    """A `base_slot` the city's workbook has no pool for is the quieter half of
    the same failure: the rule resolves against nothing and the count above
    would be zero for a reason that has nothing to do with the selector."""
    _df, pools = repository.menu_data(city)
    for rule in _prefer_with_rules(city):
        for side, slots in (('base_slot_a', rule.base_slot_a),
                            ('base_slot_b', rule.base_slot_b)):
            missing = [s for s in sorted(slots or ()) if s not in pools]
            assert not missing, (
                f'{city}/{rule.name}: {side} names {missing}, which this '
                f"city's ontology has no pool for. Available: "
                f'{sorted(pools)[:12]}...')


def test_the_combo_slot_names_are_not_forgotten():
    """The phase-1 finding, pinned where it will be read.

    A counter whose sambar shares a cell with dal keys that cell `dal_sambar`,
    never `sambar`. A sambar-targeting pairing written as `base_slot_b:
    "sambar"` is therefore inert on exactly the counters where the pair has a
    gradient — measured, 0 of 90 counters against 12 with the combo names
    included. If such a rule ever ships, it has to name the combo pools too.
    """
    for city in CITIES:
        _df, pools = repository.menu_data(city)
        for rule in _prefer_with_rules(city):
            targets = set(rule.base_slot_b or ())
            if 'sambar' not in targets:
                continue
            combos = {s for s in ('dal_sambar', 'sambar_rasam') if s in pools}
            assert combos <= targets, (
                f'{city}/{rule.name} targets `sambar` but not '
                f'{sorted(combos - targets)}. On a combo counter the sambar '
                f'lives in those pools, so the rule would be inert exactly '
                f'where it has something to do.')
