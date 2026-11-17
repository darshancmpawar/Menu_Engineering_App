"""A client's own menu layout, theme-pinned combinations, and free-text non-veg.

Built for Rippling's requirement sheet: rows in the client's order under the
client's names (T2), a veg / non-veg marker on every dish (T4), when each dish
was last served (T5), and the biryani day always rasam in the Sambar / Rasam
row. Fast: no solve here — `test_rippling_client_logic.py` runs the real one.

The first two tests are guards over the committed configs, because both keys
are read by string and a typo loads as nothing at all (CLAUDE.md, note 9).
"""

from __future__ import annotations

import datetime as dt
import io
import json
import pathlib

from src.client.client_config import AVAILABLE_THEMES
from src.constants import BASE_SLOT_NAMES, COMBO_CATEGORIES, CONST_SLOTS
from src.menu_rules.menu_rule_loader import CLIENT_RULES_DIR, MenuRuleLoader
from src.solver.menu_solver import _combo_day_variant, _combo_variant_for
from src.solver.solution_formatter import SolutionFormatter
from ui.formatters import last_served_cells, served_dates_by_item
from ui.menu_table import day_cells
from ui.planner_view import plan_xlsx

_SLOTS = set(BASE_SLOT_NAMES) | set(CONST_SLOTS)


def _client_blocks():
    for path in sorted(pathlib.Path(CLIENT_RULES_DIR).glob('*.json')):
        for name, block in json.loads(path.read_text(encoding='utf-8')).items():
            if isinstance(block, dict):
                yield path.name, name, block


def _real_slot(key: str) -> bool:
    base, _, num = key.partition('__')
    return base in _SLOTS and (not num or num.isdigit())


# --- guards over the committed configs ---------------------------------------

def test_every_display_block_names_real_slots():
    for path, name, block in _client_blocks():
        display = block.get('display')
        if not display:
            continue
        keys = list(display.get('order') or []) + [
            k for k in (display.get('labels') or {}) if not k.startswith('_')]
        bad = [k for k in keys if not _real_slot(k)]
        assert not bad, f"{path}: {name} display names unknown slots {bad}"
        # Those two are database switches now (clients.features); in a file
        # they would be read by nothing.
        for flag in ('veg_markers', 'last_served'):
            assert flag not in display, (path, flag)


def test_every_combo_by_theme_names_a_real_slot_component_and_theme():
    for path, name, block in _client_blocks():
        layers = [block] + [c for c in (block.get('counters') or {}).values()
                            if isinstance(c, dict)]
        for layer in layers:
            for slot, by_theme in (layer.get('combo_by_theme') or {}).items():
                assert slot in COMBO_CATEGORIES, (path, slot)
                for theme, half in by_theme.items():
                    assert theme in AVAILABLE_THEMES, (path, slot, theme)
                    assert half in COMBO_CATEGORIES[slot], (path, slot, half)


# --- the loader ---------------------------------------------------------------

def test_loader_reads_display_and_combo_by_theme(monkeypatch, tmp_path):
    (tmp_path / 'acme.json').write_text(json.dumps({
        'Acme': {'display': {'order': ['dal', 'rice'], 'labels': {'dal': 'Lentils', '_x': 'y'}},
                 'combo_by_theme': {'sambar_rasam': {'biryani': 'rasam'}},
                 'counters': {'Dinner': {'combo_by_theme': {'sambar_rasam': {'north': 'sambar'}}}}},
        'Broken': {'display': {'order': 'dal', 'labels': ['x']}},
    }))
    monkeypatch.setattr('src.menu_rules.menu_rule_loader.CLIENT_RULES_DIR', str(tmp_path))
    loader = MenuRuleLoader()
    assert loader.get_client_display('Acme') == {
        'order': ['dal', 'rice'], 'labels': {'dal': 'Lentils'}}
    assert loader.get_client_display('Broken') == {'order': [], 'labels': {}}
    assert loader.get_client_display('Nobody') == {}
    assert loader.get_client_combo_by_theme('Acme') == {'sambar_rasam': {'biryani': 'rasam'}}
    # A counter's entry replaces the client-level one for that combination.
    assert loader.get_client_combo_by_theme('Acme', 'Dinner') == {
        'sambar_rasam': {'north': 'sambar'}}


# --- rasam on the biryani day, wherever it falls --------------------------------

def test_the_biryani_day_keeps_rasam_across_a_fortnight():
    monday = dt.date(2026, 8, 3)
    dates = [monday + dt.timedelta(days=i) for i in range(12) if (monday + dt.timedelta(days=i)).weekday() < 5]
    themes = {'monday': 'biryani', 'tuesday': 'mix', 'wednesday': 'mix',
              'thursday': 'mix', 'friday': 'mix'}
    plain = [_combo_day_variant('sambar_rasam', i, len(dates)) for i in range(len(dates))]
    # The position split alone puts sambar on the SECOND Monday (index 5).
    assert plain[0] == 'rasam' and plain[5] == 'sambar'
    pinned = [_combo_variant_for('sambar_rasam', i, dates, themes, None,
                                 {'sambar_rasam': {'biryani': 'rasam'}})
              for i in range(len(dates))]
    assert pinned[0] == pinned[5] == 'rasam'
    assert [p for i, p in enumerate(pinned) if i not in (0, 5)] == \
        [p for i, p in enumerate(plain) if i not in (0, 5)]
    # Not one of the slot's halves: ignored, the position split stands.
    assert [_combo_variant_for('sambar_rasam', i, dates, themes, None,
                               {'sambar_rasam': {'biryani': 'dal'}})
            for i in range(len(dates))] == plain


# --- free text is read for non-veg (the vegetarian line) -----------------------

def _fmt(name, slot, known):
    d = dt.date(2026, 8, 3)
    sol = SolutionFormatter({d: {slot: name}}, [d], known_items=known,
                            nonveg_items={'chicken_65'}).to_dict()
    return sol[d.isoformat()]['items'][slot]['is_nonveg']


def test_free_text_naming_chicken_or_egg_is_non_veg():
    known = {'soya_keema_pulao', 'red_velvet_pastry_egg_less', 'paneer_tikka', 'chicken_65'}
    assert _fmt('Lettuce, carrot, millets, pesto chicken', 'salad', known)
    assert _fmt('Cut cucumber, barley, boiled egg', 'salad', known)
    assert _fmt('Kidney beans, broken wheat, boiled eggs', 'salad', known)
    assert not _fmt('Lettuce, carrot, paneer, eggplant', 'salad', known)
    assert not _fmt('Green olives, garlic yogurt dressing', 'chutney', known)
    # An ontology dish is never word-read: these are vegetarian rows.
    assert not _fmt('soya_keema_pulao', 'rice', known)
    assert not _fmt('red_velvet_pastry_egg_less', 'dessert', known)
    assert _fmt('chicken_65', 'nonveg_main', known)
    # Without the city's names the free-text step does not run.
    assert not _fmt('pesto chicken salad', 'salad', None)


# --- last served ------------------------------------------------------------------

def test_served_dates_by_item_reads_flat_and_nested_history():
    rows = [
        {'service_date': '2026-07-20', 'menu': {'dal': 'Dal_Tadka ', 'rice': 'jeera_rice'}},
        {'service_date': '2026-07-27', 'menu': {'Lunch': {'dal': 'dal_tadka'}}},
        {'service_date': '2026-07-28', 'menu': 'not a dict'},
    ]
    got = served_dates_by_item(rows)
    assert got['dal_tadka'] == [dt.date(2026, 7, 20), dt.date(2026, 7, 27)]
    assert got['jeera_rice'] == [dt.date(2026, 7, 20)]
    assert served_dates_by_item([]) == {}


def test_last_served_counts_back_from_each_cell_and_skips_staples_and_pins():
    served = {'dal_tadka': [dt.date(2026, 7, 13), dt.date(2026, 7, 27)],
              'jeera_rice': [dt.date(2026, 8, 3)]}
    plan = {
        '2026-08-03': {'dal': 'dal_tadka(Y)', 'rice': 'jeera_rice(Y)',
                       'white_rice': 'steamed rice', 'bread__1': 'plain_chapati(B)',
                       'salad': 'Lettuce, carrot', 'dessert': 'gajar_halwa(O)'},
        '2026-08-04': {'rice': 'jeera_rice(Y)'},
    }
    got = last_served_cells(plan, served, {'2026-08-03': {'bread__1'}})
    assert got['2026-08-03'] == {
        'dal': 'Last served 27 Jul (7 days ago)',
        'rice': 'New',                           # same day is not "before"
        'dessert': 'New',
    }
    assert got['2026-08-04'] == {'rice': 'Last served 3 Aug (1 day ago)'}


# --- the table and the export ----------------------------------------------------

_DISPLAY = {'order': ['salad', 'rice', 'nonveg_main__1'],
            'labels': {'salad': 'Make Your Own Salad', 'nonveg_main__1': 'NonVeg Main (Chicken)'},
            'veg_markers': True, 'last_served': True}
_PLAN = {'2026-08-03': {'nonveg_main__1': 'chicken_65(R)', 'dal': 'dal_tadka(Y)',
                        'rice': 'jeera_rice(Y)', 'salad': 'Lettuce, pesto chicken'}}
_NONVEG = {'2026-08-03': {'nonveg_main__1', 'salad'}}
_LAST = {'2026-08-03': {'rice': 'Last served 27 Jul (7 days ago)'}}


def test_table_rows_follow_the_clients_order_labels_and_markers():
    args = day_cells(_PLAN, ['2026-08-03'], {}, _NONVEG,
                     display=_DISPLAY, last_served=_LAST)
    rows = args['rows']
    # Listed rows in the client's order, an unlisted one (dal) after them.
    assert [r['id'] for r in rows] == ['salad', 'rice', 'nonveg_main__1', 'dal']
    assert [r['label'] for r in rows][:3] == ['Make Your Own Salad', 'Flavoured Rice',
                                              'NonVeg Main (Chicken)']
    cells = {r['id']: r['cells']['2026-08-03'] for r in rows}
    assert cells['salad']['marker'] == 'nonveg'
    assert cells['rice']['marker'] == 'veg'
    assert cells['rice']['last'] == 'Last served 27 Jul (7 days ago)'
    assert 'last' not in cells['dal']


def test_no_display_block_changes_nothing():
    args = day_cells(_PLAN, ['2026-08-03'], {}, _NONVEG)
    assert [r['id'] for r in args['rows']] == list(_PLAN['2026-08-03'])
    assert all('marker' not in c and 'last' not in c
               for r in args['rows'] for c in r['cells'].values())


def test_excel_uses_the_clients_layout_markers_and_last_served():
    from openpyxl import load_workbook
    block = {'name': 'Lunch', 'plan': _PLAN, 'plan_dates': ['2026-08-03'],
             'nonveg': _NONVEG, 'display': _DISPLAY, 'last_served': _LAST}
    ws = load_workbook(io.BytesIO(plan_xlsx([block], 'Rippling'))).active
    labels = [ws.cell(row=r, column=1).value for r in range(3, 7)]
    assert labels == ['Make Your Own Salad', 'Flavoured Rice',
                      'NonVeg Main (Chicken)', 'Dal']
    assert ws.cell(row=4, column=2).value == 'Jeera Rice\nLast served 27 Jul (7 days ago)'
    assert len(ws._images) == 4                  # one marker per dish
    # To the RIGHT of the name: every icon sits in column C, beside the
    # dishes in B, and the date heading spans both.
    assert {img.anchor._from.col for img in ws._images} == {2}
    assert {str(r) for r in ws.merged_cells.ranges} == {'B2:C2'}
    plain = load_workbook(io.BytesIO(plan_xlsx(
        [dict(block, display={}, last_served={})], 'X'))).active
    assert len(plain._images) == 0
    assert not plain.merged_cells.ranges         # no marker column, no merge


# --- pins per session (one counter, lunch and dinner) ---------------------------

def test_every_constant_items_by_meal_names_a_real_meal_and_slot():
    from src.history import MEALS
    for path, name, block in _client_blocks():
        layers = [block] + [c for c in (block.get('counters') or {}).values()
                            if isinstance(c, dict)]
        for layer in layers:
            for meal, pins in (layer.get('constant_items_by_meal') or {}).items():
                if meal.startswith('_'):
                    continue
                assert meal in MEALS, (path, name, meal)
                bad = [k for k in pins if not k.startswith('_') and not _real_slot(k)]
                assert not bad, (path, name, meal, bad)


def test_session_pins_layer_over_the_client_pins(monkeypatch, tmp_path):
    (tmp_path / 'acme.json').write_text(json.dumps({'Acme': {
        'constant_items': {'bread__1': 'plain chapati', 'salad': 'green salad'},
        'constant_items_by_meal': {'dinner': {'salad': 'soup bar'},
                                   'Lunch': {'chutney': 'mint'}}}}))
    monkeypatch.setattr('src.menu_rules.menu_rule_loader.CLIENT_RULES_DIR', str(tmp_path))
    loader = MenuRuleLoader()
    assert loader.get_client_constant_items('Acme') == {
        'bread__1': 'plain chapati', 'salad': 'green salad'}
    assert loader.get_client_constant_items('Acme', None, 'dinner') == {
        'bread__1': 'plain chapati', 'salad': 'soup bar'}
    # Meal names are matched case-insensitively, the way `normalize_meal` reads them.
    assert loader.get_client_constant_items('Acme', None, 'lunch')['chutney'] == 'mint'
