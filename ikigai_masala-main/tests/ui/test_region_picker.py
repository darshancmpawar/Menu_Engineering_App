"""The planner's regional-day picker, and the weekday-map helper beside it.

What matters here is the picker's HONESTY. A region a day's theme excludes, or
one the city has too few dishes for, must reach the menu *shown with its
reason* rather than dropped: a region silently absent reads as forgotten, and
the operator has no way to tell "we weighed Rajasthan and this city has three
slots of it" from "somebody broke the list".

`region_day_args` is a plain function over plain dicts, so all of that is
pinned without a browser. `_weekday_map_from_dates` still lives in `app.py`,
which a Streamlit script cannot import without a session — that one is read out
of the AST, with an assertion that it is still module-level so this fails
loudly instead of measuring nothing if it moves.
"""

from __future__ import annotations

import ast as _ast
import datetime as dt
from pathlib import Path

from ui.region_strip import region_day_args

ROOT = Path(__file__).resolve().parents[2]


def _weekday_helper():
    src = (ROOT / 'app.py').read_text()
    tree = _ast.parse(src)
    found = [n for n in tree.body
             if isinstance(n, _ast.FunctionDef) and n.name == '_weekday_map_from_dates']
    assert found, ('app.py no longer defines _weekday_map_from_dates at module '
                   'level; this test cannot reach it and is measuring nothing')
    ns = {'dt': dt}
    exec(compile(_ast.Module(body=found, type_ignores=[]), 'app.py', 'exec'), ns)
    return ns['_weekday_map_from_dates']


_weekday_map_from_dates = _weekday_helper()

META = {
    'theme_compatibility': {
        'south': ['Tamil Nadu', 'Karnataka'],
        'north': ['Punjab'],
        'mix': ['Tamil Nadu', 'Karnataka', 'Punjab'],
        'chinese': [],
    },
    'regions': [
        {'name': 'Tamil Nadu', 'deep_slots': ['a'] * 10, 'themeable': True,
         'cuisine_families': ['south_indian']},
        {'name': 'Karnataka', 'deep_slots': ['a'] * 11, 'themeable': True,
         'cuisine_families': ['south_indian']},
        {'name': 'Punjab', 'deep_slots': ['a'] * 6, 'themeable': True,
         'cuisine_families': ['north_indian']},
        {'name': 'Rajasthan', 'deep_slots': ['a'] * 3, 'themeable': False,
         'cuisine_families': ['north_indian']},
    ],
}
MON, TUE = '2026-09-21', '2026-09-22'


def _day(theme, **kw):
    return region_day_args(META, [MON], {MON: theme}, city='Bangalore', **kw)[0]


class TestWhatTheMenuOffers:
    def test_a_south_day_offers_only_the_south_regions(self):
        d = _day('south')
        assert [o['name'] for o in d['options']] == [
            'No region', 'Tamil Nadu', 'Karnataka']

    def test_an_offered_region_carries_its_depth(self):
        """The number is the argument for the choice, so it sits beside the
        name rather than in a tooltip nobody opens."""
        d = _day('south')
        assert {o['name']: o['meta'] for o in d['options']}['Karnataka'] == '11 slots'

    def test_a_wrong_cuisine_region_is_shown_greyed_with_its_family(self):
        d = _day('south')
        assert {w['name']: w['meta'] for w in d['wrong']} == {
            'Punjab': 'North Indian'}
        assert 'South' in d['wrong_label']

    def test_a_thin_region_is_named_in_the_footer_not_dropped(self):
        """Greyed and counted rather than hidden — otherwise an operator cannot
        tell a weighed-and-rejected region from a missing one."""
        d = _day('mix')
        assert 'Rajasthan' in d['thin']
        assert 'Bangalore' in d['thin_label']

    def test_every_region_reaches_the_menu_somewhere(self):
        """The guarantee the whole component exists for: offered, greyed as
        wrong-cuisine, or named as too thin — never simply absent."""
        for theme in ('south', 'north', 'mix', 'chinese'):
            d = _day(theme)
            seen = ({o['name'] for o in d['options'] if o['value']}
                    | {w['name'] for w in d['wrong']}
                    | set(d['thin'].replace(' and 0 more', '').split(', ')))
            for r in META['regions']:
                assert r['name'] in seen, (theme, r['name'])

    def test_a_flag_narrowed_theme_takes_no_region_at_all(self):
        """chinese / biryani / continental narrow the mains by FLAG, so a
        region's dishes are gone before any floor could be read. The chip is
        disabled and says why, rather than opening an empty menu."""
        d = _day('chinese')
        assert d['disabled'] and 'no region fits' in d['title']

    def test_an_unknown_theme_offers_nothing_rather_than_everything(self):
        """Fail closed: a theme the compatibility map has not heard of must not
        silently offer every region."""
        assert _day('holiday')['disabled']

    def test_no_region_is_always_an_option_so_a_day_can_be_cleared(self):
        d = _day('south')
        assert d['options'][0] == {'value': '', 'name': 'No region',
                                   'meta': 'theme only'}

    def test_empty_metadata_disables_the_day_rather_than_raising(self):
        d = region_day_args({}, [MON], {MON: 'south'})[0]
        assert d['disabled'] and d['wrong'] == [] and d['thin'] == ''


class TestWhatTheChipSays:
    def test_the_chip_names_the_day_and_its_theme(self):
        assert _day('south')['chip'] == 'MON · SOUTH'

    def test_an_applied_region_is_carried_so_the_chip_can_colour_itself(self):
        d = region_day_args(META, [MON], {MON: 'south'},
                            applied={MON: 'Tamil Nadu'})[0]
        assert d['applied'] == 'Tamil Nadu' and not d['below_floor']

    def test_a_day_the_solver_could_not_honour_is_flagged(self):
        """`region_problems` name their date, so the chip for THAT day can say
        the pick did not hold — rather than one warning over the whole week."""
        d = region_day_args(META, [MON], {MON: 'south'},
                            applied={MON: 'Tamil Nadu'},
                            problems=[{'date': MON, 'message': 'too thin'}])[0]
        assert d['below_floor']

    def test_another_day_s_problem_does_not_flag_this_one(self):
        d = region_day_args(META, [MON], {MON: 'south'},
                            applied={MON: 'Tamil Nadu'},
                            problems=[{'date': TUE, 'message': 'too thin'}])[0]
        assert not d['below_floor']


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
