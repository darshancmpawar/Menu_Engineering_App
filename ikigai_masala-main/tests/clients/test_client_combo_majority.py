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
from src.solver.menu_solver import _combo_day_variant


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
