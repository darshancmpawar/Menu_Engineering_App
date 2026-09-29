"""`combo_majority`: which half of a combination category leads, per counter.

A combination category is ONE visible slot that alternates between two
component course_types across the week. `COMBO_CATEGORIES` picks which half
gets the majority of the days globally — dal leads `dal_sambar`, rasam leads
`sambar_rasam` — and a site wanting the other half on three days had no way to
say so.

`combo_majority` on a client block says so. It is a config key read by string,
which is the expensive failure this repo keeps naming (note 9): a typo loads as
nothing at all while `/plan` still answers 200 and the menu looks fine. So the
runtime falls back to the global order for anything it does not recognise —
planning must not stop for a typo — and **this file is what makes the typo
visible instead**.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from src.constants import COMBO_CATEGORIES
from src.menu_rules.menu_rule_loader import CLIENT_RULES_DIR, MenuRuleLoader
from src.solver.menu_solver import _combo_day_variant, _combo_variant_cells


def _client_blocks():
    """``(path, client name, block)`` for every committed client rules file."""
    for path in sorted(pathlib.Path(CLIENT_RULES_DIR).glob('*.json')):
        blob = json.loads(path.read_text())
        for name, block in blob.items():
            if isinstance(block, dict):
                yield path, name, block


def _declared(block):
    """Every ``combo_majority`` in a block, client-level and per-counter."""
    out = [('<client>', block.get('combo_majority') or {})]
    for counter, scoped in (block.get('counters') or {}).items():
        if isinstance(scoped, dict):
            out.append((counter, scoped.get('combo_majority') or {}))
    return [(where, m) for where, m in out if m]


# --- the guard, over the committed configs --------------------------------

def test_every_declared_combo_majority_names_a_real_slot_and_component():
    """A key that is not a combination category, or a value that is not one of
    that category's own two components, silently does nothing at runtime."""
    for path, name, block in _client_blocks():
        for where, mapping in _declared(block):
            for slot, component in mapping.items():
                assert slot in COMBO_CATEGORIES, (
                    f"{path.name}: {name}/{where} sets combo_majority for "
                    f"{slot!r}, which is not a combination category "
                    f"({sorted(COMBO_CATEGORIES)})")
                assert component in COMBO_CATEGORIES[slot], (
                    f"{path.name}: {name}/{where} wants {component!r} to lead "
                    f"{slot!r}, whose components are "
                    f"{COMBO_CATEGORIES[slot]}")


def test_a_counter_declaring_it_actually_serves_the_slot():
    """Setting it for a slot the counter does not run is a no-op nobody would
    notice. Read off the live client rows rather than the config, because that
    is where the counter's categories live."""
    from tests.client_fixtures import CLIENTS
    rows = {c['name']: c for c in CLIENTS}
    for path, name, block in _client_blocks():
        declared = _declared(block)
        if not declared or name not in rows:
            continue
        served = {s for counter in rows[name]['counters']
                  for s in (counter.get('slot_counts') or {})}
        for where, mapping in declared:
            for slot in mapping:
                assert slot in served, (
                    f"{path.name}: {name}/{where} sets combo_majority for "
                    f"{slot!r}, but no counter on this client serves it")


# --- the behaviour it buys ------------------------------------------------

def test_unset_keeps_the_global_order():
    """The default, and the reason this ships inert: no client has asked yet."""
    for combo, (majority, _minority) in COMBO_CATEGORIES.items():
        assert _combo_day_variant(combo, 0, 5) == majority
        assert _combo_day_variant(combo, 0, 5, {}) == majority
        assert _combo_day_variant(combo, 0, 5, None) == majority


def test_naming_the_other_component_swaps_which_half_leads():
    days = 5
    for combo, (majority, minority) in COMBO_CATEGORIES.items():
        default = [_combo_day_variant(combo, d, days) for d in range(days)]
        swapped = [_combo_day_variant(combo, d, days, {combo: minority})
                   for d in range(days)]
        assert default.count(majority) == 3 and default.count(minority) == 2
        assert swapped.count(minority) == 3 and swapped.count(majority) == 2
        # Still alternating, which is the client rule the split exists for.
        assert all(a != b for a, b in zip(swapped, swapped[1:])) or days < 3


@pytest.mark.parametrize('bad', ['rasam', 'nonsense', '', None])
def test_an_unrecognised_component_falls_back_rather_than_raising(bad):
    """A typo must not take planning down — it degrades to the global order,
    which is why the guards above exist to catch it instead."""
    got = [_combo_day_variant('dal_sambar', d, 5, {'dal_sambar': bad})
           for d in range(5)]
    assert got == [_combo_day_variant('dal_sambar', d, 5) for d in range(5)]


def test_it_reaches_the_solver_config_from_a_client_block(monkeypatch, tmp_path):
    """The whole path: a client file says it, the loader reads it, and the
    value the solver reads back is the same one."""
    (tmp_path / 'acme.json').write_text(json.dumps({
        'Acme': {'combo_majority': {'dal_sambar': 'sambar'},
                 'counters': {'Counter 2': {
                     'combo_majority': {'dal_sambar': 'dal'}}}},
    }))
    monkeypatch.setattr(
        'src.menu_rules.menu_rule_loader.CLIENT_RULES_DIR', str(tmp_path))
    loader = MenuRuleLoader()
    assert loader.get_client_combo_majority('Acme') == {'dal_sambar': 'sambar'}
    # A counter entry layers over the client-level one.
    assert loader.get_client_combo_majority('Acme', 'Counter 2') == {
        'dal_sambar': 'dal'}
    assert loader.get_client_combo_majority('Nobody') == {}


class TestAThinComponentMustNotPinTheSlot:
    """The split is a preference; it must never make the counter impossible.

    NCR's corrected list leaves ONE sambar row. A five-day week gives
    `dal_sambar` two minority days, the narrowing pinned both to that single
    dish, and no-repetition made the whole Junglee counter INFEASIBLE — while
    pre-flight reported `would_succeed: True` with zero warnings, because
    `pool_size_diagnostics` walks `BASE_SLOT_NAMES` and `dal_sambar` is not
    one of them. One dish was strictly worse than none, since at zero the old
    `len(v) > 0` guard already fell back to the whole pair.
    """

    def test_the_minority_day_count_is_what_must_be_covered(self):
        # Five days: dal on three, sambar on two.
        assert _combo_variant_cells('dal_sambar', 'sambar', 5) == 2
        assert _combo_variant_cells('dal_sambar', 'dal', 5) == 3
        # Two cells of the slot doubles both.
        assert _combo_variant_cells('dal_sambar', 'sambar', 5, slot_count=2) == 4
        # and the counter's own choice of leader swaps them
        assert _combo_variant_cells(
            'dal_sambar', 'sambar', 5, majority_by_slot={'dal_sambar': 'sambar'}) == 3

    def test_every_combo_day_is_accounted_for(self):
        """The two components must add up to the horizon, or a day is being
        planned from a component nobody counted."""
        for combo, (majority, minority) in COMBO_CATEGORIES.items():
            for n in (3, 5, 6, 7):
                got = (_combo_variant_cells(combo, majority, n)
                       + _combo_variant_cells(combo, minority, n))
                assert got == n, (combo, n, got)


class TestARepeatableComponentNeedsOneDish:
    """Owner's ruling: "if we have sambar it can repeat."

    Two halves that only work together, which is why they are asserted
    together. `repeatable_row` has to recognise a sambar wherever it is served
    — by COURSE TYPE, because inside `dal_sambar` the cell's base slot is
    `dal_sambar` and a slot-keyed entry never sees it. And the narrowing
    threshold has to know that a repeatable component needs ONE dish rather
    than one per cell, or the permission is granted and then never used: the
    combination would still back off and NCR would serve dal five days a week
    off its single sambar row.
    """

    def test_a_sambar_is_repeatable_wherever_it_is_served(self):
        from src.constants import repeatable_row
        sambar = {'item': 'sambar_masala', 'course_type': 'sambar'}
        for slot in ('sambar', 'dal_sambar', 'sambar_rasam', None):
            assert repeatable_row(sambar, slot), slot

    def test_the_other_half_of_each_combination_is_not(self):
        """Permission is scoped. A dal must still vary day to day."""
        from src.constants import repeatable_row
        assert not repeatable_row(
            {'item': 'dal_tadka', 'course_type': 'dal'}, 'dal_sambar')
        assert not repeatable_row(
            {'item': 'jeera_rasam', 'course_type': 'rasam'}, 'sambar_rasam')

    def test_one_sambar_covers_every_day_the_combination_gives_it(self):
        """The threshold. Cells still say 2; what changes is what covers them."""
        from src.constants import REPEATABLE_COURSE_TYPES
        assert 'sambar' in REPEATABLE_COURSE_TYPES
        assert _combo_variant_cells('dal_sambar', 'sambar', 5) == 2
        # ...and `dal`, which is not repeatable, still needs its three.
        assert 'dal' not in REPEATABLE_COURSE_TYPES
        assert _combo_variant_cells('dal_sambar', 'dal', 5) == 3
