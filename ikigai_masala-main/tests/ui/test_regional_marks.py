"""Which dishes make a day regional, and how the table says so.

A regional day is a FLOOR, not a filter (v2.05.00): asking for a Maharashtra
Thursday serves at least N Maharashtrian dishes and leaves the rest of the
plate ordinary. So the day holds regional dishes beside ordinary ones and
nothing about the menu says which is which — `state_origin` is the only thing
that knows, and the planner never had it.

Two halves, tested apart because they fail apart:

  * `regional_dishes_by_date` answers WHICH, from the ontology;
  * `day_cells` turns that answer into a mark on the right cell.

The second half is where this broke first. The flat plan carries the solver's
colour suffix (`khandeshi_khichadi(R)`) and the server answers the ontology
spelling (`khandeshi_khichadi`); compared raw they never match, so every cell
came back unmarked with nothing raised — the day looked ordinary and the
feature looked built.
"""

from __future__ import annotations

import pandas as pd

from src.ontology.regions import regional_dishes_by_date
from ui.menu_table import day_cells

DAY = '2026-11-05'
OTHER = '2026-11-04'

DF = pd.DataFrame({
    'item': ['khandeshi_khichadi', 'kanada_pithala', 'masala_paratha', 'miso_soup'],
    'state_origin': ['Maharashtra', 'Maharashtra', 'Pan-North India', ''],
})


def _solution(**slots):
    return {DAY: {'items': {s: {'item_base': v} for s, v in slots.items()}}}


class TestWhichDishesAreRegional:
    def test_only_the_dishes_from_that_region(self):
        got = regional_dishes_by_date(
            DF, _solution(rice='khandeshi_khichadi', bread='masala_paratha'),
            {DAY: 'Maharashtra'})
        assert got == {DAY: ['khandeshi_khichadi']}

    def test_a_day_with_none_is_absent_rather_than_empty(self):
        """An empty list and a missing key read the same to the table, and the
        absent key keeps the response byte-identical for a plan nobody asked a
        region for."""
        got = regional_dishes_by_date(DF, _solution(bread='masala_paratha'),
                                      {DAY: 'Maharashtra'})
        assert got == {}

    def test_the_region_name_is_matched_loosely(self):
        """'maharashtra' against a column holding 'Maharashtra' is the near
        miss that resolves to nothing while everything still answers 200."""
        got = regional_dishes_by_date(DF, _solution(rice='khandeshi_khichadi'),
                                      {DAY: '  maharashtra '})
        assert got == {DAY: ['khandeshi_khichadi']}

    def test_no_region_column_is_not_a_crash(self):
        assert regional_dishes_by_date(DF.drop(columns=['state_origin']),
                                       _solution(rice='khandeshi_khichadi'),
                                       {DAY: 'Maharashtra'}) == {}

    def test_nothing_asked_nothing_answered(self):
        assert regional_dishes_by_date(DF, _solution(rice='x'), {}) == {}


class TestTheTableMarksThem:
    PLAN = {DAY: {'rice': 'khandeshi_khichadi(R)', 'bread': 'masala_paratha(B)'},
            OTHER: {'rice': 'khandeshi_khichadi(R)', 'bread': 'masala_paratha(B)'}}

    def _cells(self, **kw):
        args = day_cells(self.PLAN, [OTHER, DAY], {OTHER: 'north', DAY: 'north'}, **kw)
        return {r['id']: r['cells'] for r in args['rows']}, args['days']

    def test_the_colour_suffix_does_not_defeat_the_match(self):
        """The bug this file exists for: `khandeshi_khichadi(R)` in the plan
        against `khandeshi_khichadi` from the server marked nothing."""
        rows, _ = self._cells(regions={DAY: 'Maharashtra'},
                              regional_dishes={DAY: ['khandeshi_khichadi']})
        assert rows['rice'][DAY]['regional'] is True

    def test_an_ordinary_dish_on_a_regional_day_is_not_marked(self):
        """The floor is the whole point — most of a regional day is ordinary."""
        rows, _ = self._cells(regions={DAY: 'Maharashtra'},
                              regional_dishes={DAY: ['khandeshi_khichadi']})
        assert rows['bread'][DAY]['regional'] is False

    def test_the_same_dish_on_a_non_regional_day_is_not_marked(self):
        rows, _ = self._cells(regions={DAY: 'Maharashtra'},
                              regional_dishes={DAY: ['khandeshi_khichadi']})
        assert rows['rice'][OTHER]['regional'] is False

    def test_the_day_header_names_the_region(self):
        _rows, days = self._cells(regions={DAY: 'Maharashtra'},
                                  regional_dishes={DAY: ['khandeshi_khichadi']})
        by_iso = {d['iso']: d for d in days}
        assert by_iso[DAY]['region'] == 'Maharashtra'
        assert not by_iso[OTHER]['region']
        # the theme is still there; the region is additional, not a replacement
        assert by_iso[DAY]['theme_label'] == 'North'

    def test_a_plan_with_no_region_marks_nothing(self):
        rows, days = self._cells()
        assert not any(c['regional'] for cells in rows.values() for c in cells.values())
        assert not any(d['region'] for d in days)


if __name__ == '__main__':      # a runnable check without pytest
    import pytest
    raise SystemExit(pytest.main([__file__, '-q']))


class TestTheMarkerIsStillVisible:
    """The R's style is load-bearing and invisible to every test above.

    It reads across a wide table only because it is a filled dark disc with
    white text; it sits at the right edge only because of two CSS rules that
    work as a pair. Drop either and the mark drifts into the middle of the
    cell beside the dish name — a layout regression no data test can see, and
    one nobody would notice in a diff. Verified in a real browser once; this
    is what stops it being quietly undone.
    """

    @staticmethod
    def _css():
        import pathlib
        return (pathlib.Path(__file__).resolve().parents[2]
                / 'ui' / 'menu_table' / 'index.html').read_text()

    def test_it_is_a_dark_disc_with_white_text(self):
        css = self._css()
        assert 'border-radius: 50%; background: #131313; color: #FFFFFF;' in css

    def test_it_is_pushed_to_the_right_edge(self):
        assert '.cell .rgn { margin-left: auto;' in self._css()

    def test_a_marker_beside_it_does_not_get_a_second_auto_margin(self):
        """Two `auto` margins split the free space between them, which strands
        the R mid-cell whenever a tick, warning or redo shares the row."""
        assert '.cell .rgn + .tail { margin-left: 4px; }' in self._css()
