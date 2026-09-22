"""The planner's regional-day helpers.

A Streamlit script cannot be imported without a session, so the pure helpers
are read out of `app.py`'s AST and executed — the same trick
`test_meal_difference.py` uses, with the same assertion that they are still
module-level, so this fails loudly instead of measuring nothing if they move.

What matters here is the PICKER's honesty. A region that a day's theme
excludes, or that the city has too few dishes for, must come back *disabled
with its reason* rather than missing: a region silently absent from a dropdown
reads as forgotten, and the operator has no way to tell "we considered
Rajasthan and Bangalore has three slots of it" from "somebody broke the list".
"""

from __future__ import annotations

import ast as _ast
import datetime as dt
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _planner_helpers():
    src = (ROOT / 'app.py').read_text()
    tree = _ast.parse(src)
    wanted = {'_region_options', '_weekday_map_from_dates'}
    found = [n for n in tree.body
             if isinstance(n, _ast.FunctionDef) and n.name in wanted]
    assert {n.name for n in found} == wanted, (
        'app.py no longer defines both helpers at module level; this test '
        'cannot reach them and is measuring nothing')
    ns = {'dt': dt}
    exec(compile(_ast.Module(body=found, type_ignores=[]), 'app.py', 'exec'), ns)
    return ns['_region_options'], ns['_weekday_map_from_dates']


_region_options, _weekday_map_from_dates = _planner_helpers()


META = {
    'theme_compatibility': {
        'south': ['Tamil Nadu', 'Karnataka'],
        'north': ['Punjab'],
        'mix': ['Tamil Nadu', 'Karnataka', 'Punjab'],
        'chinese': [],
    },
    'regions': [
        {'name': 'Tamil Nadu', 'deep_slots': ['a'] * 10, 'themeable': True},
        {'name': 'Karnataka', 'deep_slots': ['a'] * 11, 'themeable': True},
        {'name': 'Punjab', 'deep_slots': ['a'] * 6, 'themeable': True},
        {'name': 'Rajasthan', 'deep_slots': ['a'] * 3, 'themeable': False},
    ],
}


def _by_name(options):
    return {name: (label, disabled) for name, label, disabled in options}


class TestWhatThePickerOffers:
    def test_a_south_day_enables_only_the_south_regions(self):
        got = _by_name(_region_options(META, 'south'))
        assert got['Tamil Nadu'][1] is False
        assert got['Karnataka'][1] is False
        assert got['Punjab'][1] is True

    def test_the_enabled_ones_carry_their_depth(self):
        """The number is the argument for the choice, so it belongs in the
        label rather than in a tooltip nobody opens."""
        label, disabled = _by_name(_region_options(META, 'south'))['Karnataka']
        assert '11' in label and not disabled

    def test_a_wrong_cuisine_region_says_why(self):
        label, disabled = _by_name(_region_options(META, 'south'))['Punjab']
        assert disabled
        assert 'cuisine' in label.lower() and 'south' in label.lower()

    def test_a_thin_region_says_how_thin(self):
        """Offered greyed rather than hidden, with its count — otherwise an
        operator cannot tell a weighed-and-rejected region from a missing one."""
        label, disabled = _by_name(_region_options(META, 'mix'))['Rajasthan']
        assert disabled
        assert '3' in label

    def test_nothing_is_ever_dropped_from_the_list(self):
        for theme in ('south', 'north', 'mix', 'chinese'):
            assert len(_region_options(META, theme)) == len(META['regions'])

    def test_a_flag_narrowed_theme_enables_nothing(self):
        """chinese / biryani / continental narrow the main slots by FLAG, so a
        region's dishes are gone before any floor could be read. The planner
        reads 'no enabled option' as 'this day takes no region'."""
        assert all(d for _, _, d in _region_options(META, 'chinese'))

    def test_enabled_options_come_first(self):
        """The list is long and mostly unusable; the choices go on top."""
        flags = [d for _, _, d in _region_options(META, 'mix')]
        assert flags == sorted(flags), 'disabled options must sort last'

    def test_an_unknown_theme_enables_nothing_rather_than_everything(self):
        """Fail closed: a theme the compatibility map has not heard of must not
        silently offer every region."""
        assert all(d for _, _, d in _region_options(META, 'holiday'))

    def test_empty_metadata_yields_no_options(self):
        assert _region_options({}, 'south') == []


class TestSavingAsAWeeklyDefault:
    def test_dates_become_weekdays(self):
        assert _weekday_map_from_dates({'2026-09-24': 'Tamil Nadu'}) == {
            'thursday': 'Tamil Nadu'}

    def test_the_later_date_wins_a_repeated_weekday(self):
        """A fortnight holds two Thursdays. The more recent pick is the more
        recent decision."""
        got = _weekday_map_from_dates({'2026-09-24': 'Tamil Nadu',
                                       '2026-10-01': 'Karnataka'})
        assert got == {'thursday': 'Karnataka'}

    def test_a_junk_date_is_skipped_not_fatal(self):
        assert _weekday_map_from_dates({'nonsense': 'X',
                                        '2026-09-25': 'Punjab'}) == {
            'friday': 'Punjab'}

    def test_nothing_in_nothing_out(self):
        assert _weekday_map_from_dates({}) == {}
