"""The pure table functions behind Pick: replay safety, keys, and payload size.

Every one of these failed quietly in its `regenerate` twin at some point, and
the failures are the reason the twin's docstring is as long as it is: a
component's return value is REPLAYED on every rerun, and a cell key split the
wrong way round produces a valid-looking dict that names no cell the plan has.
Pick inherits both hazards, so it inherits the tests.

No Streamlit, no network, no solver.
"""

from __future__ import annotations

import pandas as pd
import pytest

from ui.menu_table import (
    day_cells, dish_payload, manual_cells_from, merged_exceptions,
    pick_request, same_dish,
)


class TestReplaySafety:
    """One press is one request. Without this the table picks forever."""

    def test_a_pick_is_returned_once(self):
        got = {'action': 'pick', 'cell': 'veg_gravy|2026-11-02',
               'item': 'paneer_lababdar', 'nonce': 17}
        first = pick_request(got, None)
        assert first == {'nonce': 17, 'cell': ('veg_gravy', '2026-11-02'),
                         'item': 'paneer_lababdar'}
        assert pick_request(got, first['nonce']) is None, (
            'the same nonce came back a second time — this is the infinite '
            'rerun loop the nonce exists to stop')

    def test_a_new_pick_after_a_handled_one_is_returned(self):
        """The negative half: the guard must not swallow the next pick."""
        assert pick_request(
            {'action': 'pick', 'cell': 'rice|2026-11-02', 'item': 'x',
             'nonce': 18}, 17) is not None

    @pytest.mark.parametrize('payload', [
        None, {}, 'pick', {'action': 'regenerate', 'cells': ['a|b']},
        {'action': 'pick', 'cell': 'veg_gravy|2026-11-02'},          # no item
        {'action': 'pick', 'cell': 'veg_gravy', 'item': 'x'},        # no date
        {'action': 'pick', 'cell': '|2026-11-02', 'item': 'x'},      # no slot
        {'action': 'pick', 'cell': 'veg_gravy|2026-11-02', 'item': '  '},
    ])
    def test_anything_malformed_is_no_request(self, payload):
        assert pick_request(payload) is None


def test_the_cell_key_splits_the_way_the_table_joined_it():
    """`<slot>|<iso>`, never the other way round.

    Reversed, the pair still looks like a cell and `/pick` answers 400
    `unknown_cell` — but only because the server checks. The bug is silent in
    every layer before it.
    """
    out = pick_request({'action': 'pick', 'cell': 'nonveg_main__2|2026-11-05',
                        'item': 'fish_curry', 'nonce': 1})
    assert out['cell'] == ('nonveg_main__2', '2026-11-05')


class TestManualCells:
    def test_both_server_shapes_are_unioned(self):
        """`manual_cells` is what was picked, `exceptions` the subset that
        broke something. A cell in either is a cell a planner chose."""
        got = manual_cells_from(
            exceptions=[{'date': '2026-11-03', 'slot_id': 'rice'}],
            manual={'2026-11-02': ['veg_gravy'], '2026-11-03': ['rice']})
        assert got == {'rice|2026-11-03', 'veg_gravy|2026-11-02'}

    def test_empty_is_empty(self):
        assert manual_cells_from(None, None) == set()


def test_day_cells_marks_manual_separately_from_pinned():
    """Two markers, because only one of them can be undone.

    Pinned means the client's configuration fixed the cell; manual means a
    person overrode it. Collapsing them into one marker would tell the planner
    a cell they can still change is fixed.
    """
    plan = {'2026-11-02': {'veg_gravy': 'paneer_lababdar(R)',
                           'white_rice': 'steamed_rice'}}
    args = day_cells(plan, ['2026-11-02'], {'2026-11-02': 'mix'},
                     pinned={'white_rice|2026-11-02'},
                     manual={'veg_gravy|2026-11-02'})
    cells = {r['id']: r['cells']['2026-11-02'] for r in args['rows']}
    assert cells['veg_gravy']['manual'] is True
    assert cells['veg_gravy']['pinned'] is False
    assert cells['white_rice']['pinned'] is True
    assert cells['white_rice']['manual'] is False


class TestMergedExceptions:
    """The panel accumulates across requests; the server does not.

    `/pick` is stateless and answers only about the request in hand, so a
    plain `existing + new` is wrong in two opposite directions and both leave
    the planner reading about a plate nobody is serving.
    """

    def _result(self, date, slot, violations):
        entry = {"date": date, "slot_id": slot, "item": "x",
                 "violations": violations}
        return {"manual_cells": {date: [slot]},
                "exceptions": [entry] if violations else []}

    def test_a_second_pick_on_one_cell_replaces_its_entry(self):
        first = merged_exceptions(
            [], self._result("2026-11-02", "veg_gravy", [{"code": "cooldown"}]))
        assert len(first) == 1
        again = merged_exceptions(
            first,
            self._result("2026-11-02", "veg_gravy", [{"code": "client_pool"}]))
        assert len(again) == 1, "the panel stacked a second entry for one cell"
        assert again[0]["violations"][0]["code"] == "client_pool"

    def test_a_clean_pick_clears_the_cells_old_entry(self):
        """The half `existing + new` misses: fixing your own mistake must
        remove the warning, not leave it beside the corrected dish."""
        dirty = merged_exceptions(
            [], self._result("2026-11-02", "veg_gravy", [{"code": "cooldown"}]))
        clean = merged_exceptions(
            dirty, self._result("2026-11-02", "veg_gravy", []))
        assert clean == []

    def test_other_cells_are_kept(self):
        """The negative half: clearing must be scoped to the picked cell."""
        a = merged_exceptions(
            [], self._result("2026-11-02", "veg_gravy", [{"code": "cooldown"}]))
        b = merged_exceptions(
            a, self._result("2026-11-03", "rice", [{"code": "client_pool"}]))
        assert [(e["date"], e["slot_id"]) for e in b] == [
            ("2026-11-02", "veg_gravy"), ("2026-11-03", "rice")]

    def test_nothing_in_nothing_out(self):
        assert merged_exceptions(None, None) == []


class TestSameDish:
    """Telling an undo from an ordinary pick.

    The plan stores `jeera_rice(Y)` and a pick sends `jeera_rice`, so a raw
    `==` says they differ and every undo would be filed as a new pick —
    leaving the pencil marker, the Exceptions entry and the undo stack on a
    cell the solver owns again.
    """

    @pytest.mark.parametrize('a,b', [
        ('jeera_rice(Y)', 'jeera_rice'),
        ('jeera_rice', 'jeera_rice(Y)'),
        (' Jeera_Rice (Y)', 'jeera_rice'),
        ('jeera_rice', 'jeera_rice'),
    ])
    def test_the_colour_suffix_and_case_do_not_make_two_dishes(self, a, b):
        assert same_dish(a, b)

    @pytest.mark.parametrize('a,b', [
        ('jeera_rice', 'lemon_rice'),
        ('jeera_rice', ''),
        ('', 'jeera_rice'),
        ('', ''),
        (None, None),
    ])
    def test_different_or_missing_is_not_the_same_dish(self, a, b):
        # An empty cell must never read as "the same dish": that would file a
        # pick into a blank cell as an undo and silently drop its marker.
        assert not same_dish(a, b)


class TestDishPayload:
    def _pools(self):
        return {'veg_gravy': pd.DataFrame(
            {'item': ['paneer_lababdar', 'kadai_paneer', 'dal_makhani']})}

    def test_names_are_sent_and_display_names_are_not(self):
        """The display name is derivable, and sending it doubled the payload.

        Measured on the fleet's widest counter: 342 KiB with display names,
        106 KiB without. Streamlit resends component arguments on every
        rerun, so this is per rerun, not once.
        """
        got = dish_payload(self._pools())
        assert got['veg_gravy']['n'] == [
            'paneer_lababdar', 'kadai_paneer', 'dal_makhani']
        assert 'd' not in got['veg_gravy']

    def test_out_of_pool_dishes_are_indices_and_omitted_when_none(self):
        pools = self._pools()
        client = {'veg_gravy': pd.DataFrame({'item': ['paneer_lababdar',
                                                      'kadai_paneer']})}
        got = dish_payload(pools, client_pools=client)
        assert got['veg_gravy']['out'] == [2]
        # Every dish in the client's pool -> the key is absent, not an empty
        # list. Most slots of most clients are this case (note 15).
        whole = dish_payload(pools, client_pools=pools)
        assert 'out' not in whole['veg_gravy']

    def test_recency_is_keyed_only_for_dishes_in_the_window(self):
        got = dish_payload(self._pools(), recency={'kadai_paneer': 6})
        assert got['veg_gravy']['ago'] == {'1': 6}

    def test_an_empty_pool_is_skipped(self):
        got = dish_payload({'veg_gravy': pd.DataFrame({'item': []})})
        assert got == {}


if __name__ == '__main__':      # a runnable check without pytest
    raise SystemExit(pytest.main([__file__, '-q']))
