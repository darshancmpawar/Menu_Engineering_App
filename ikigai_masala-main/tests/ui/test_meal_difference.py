"""Lunch and dinner must not be the same menu.

The client's rule: a dish served at lunch comes back only after at least two
weeks, and the two services must not be the same menu — "35-40% should be
different".

Measured on a real 5-day solve, same-day exclusion alone already gives 97%
different with ZERO lunch dishes reappearing on another day. So the floor never
binds. It is checked anyway, because a guarantee nothing measures is a
guarantee that quietly stops holding the first time a pool goes thin.
"""

from ui.formatters import (
    dishes_from_solution, meal_difference, MIN_MEAL_DIFFERENCE,
)


def _sol(days):
    """`{date: {slot: dish}}` -> a /plan-shaped solution."""
    return {
        d: {'items': {s: {'item_base': dish} for s, dish in slots.items()}}
        for d, slots in days.items()
    }


class TestTheExclusionPayload:
    def test_every_dish_is_sent_for_every_date(self):
        """The union, not each dish on its own day.

        `unique_items` works inside ONE solve, and lunch and dinner are two.
        Nothing else stops Monday's lunch dal appearing at Wednesday's dinner
        within a single generation — the cooldown only catches it after the
        plan is saved, which is after it is on screen.
        """
        out = dishes_from_solution(_sol({
            '2026-09-21': {'dal__1': 'dal_tadka'},
            '2026-09-22': {'dal__1': 'dal_fry'},
        }))
        assert set(out) == {'2026-09-21', '2026-09-22'}
        for day in out.values():
            assert day == ['dal_fry', 'dal_tadka']

    def test_staples_are_not_stripped_here(self):
        """They do not need to be. The exclusion is merged into
        `banned_by_date`, and the item-cooldown pre-filter exempts a declared
        staple from that map — so the daily curd still repeats at dinner."""
        out = dishes_from_solution(_sol({'2026-09-21': {'curd__1': 'nandini_curd'}}))
        assert out['2026-09-21'] == ['nandini_curd']

    def test_an_empty_plan_sends_nothing(self):
        assert dishes_from_solution({}) == {}
        assert dishes_from_solution({'2026-09-21': {'items': {}}}) == {}

    def test_a_bare_string_payload_is_read(self):
        assert dishes_from_solution(
            {'d': {'items': {'rice__1': 'jeera_rice'}}}) == {'d': ['jeera_rice']}


class TestTheDifferenceMeasure:
    def test_a_completely_different_dinner_is_one(self):
        lunch = _sol({'d': {'rice__1': 'a', 'dal__1': 'b'}})
        dinner = _sol({'d': {'rice__1': 'x', 'dal__1': 'y'}})
        assert meal_difference(lunch, dinner)['overall'] == 1.0

    def test_an_identical_dinner_is_zero_and_flagged(self):
        lunch = _sol({'d': {'rice__1': 'a', 'dal__1': 'b'}})
        out = meal_difference(lunch, lunch)
        assert out['overall'] == 0.0
        assert out['below_floor'] == ['d']

    def test_a_repeated_staple_does_not_sink_the_day(self):
        # The realistic shape: curd and chapati repeat, everything else moves.
        lunch = _sol({'d': {'rice__1': 'a', 'dal__1': 'b', 'veg_dry__1': 'c',
                            'curd__1': 'curd', 'bread__1': 'chapati'}})
        dinner = _sol({'d': {'rice__1': 'x', 'dal__1': 'y', 'veg_dry__1': 'z',
                             'curd__1': 'curd', 'bread__1': 'chapati'}})
        out = meal_difference(lunch, dinner)
        assert out['overall'] == 0.6
        assert out['below_floor'] == []

    def test_the_floor_is_the_clients_number(self):
        assert 0.35 <= MIN_MEAL_DIFFERENCE <= 0.40

    def test_it_is_scored_per_day_not_just_overall(self):
        # One bad day inside a good week has to be visible; an average hides it.
        lunch = _sol({'mon': {'rice__1': 'a'}, 'tue': {'rice__1': 'b'}})
        dinner = _sol({'mon': {'rice__1': 'a'}, 'tue': {'rice__1': 'z'}})
        out = meal_difference(lunch, dinner)
        assert out['per_day'] == {'mon': 0.0, 'tue': 1.0}
        assert out['below_floor'] == ['mon']

    def test_a_day_dinner_does_not_serve_is_skipped(self):
        lunch = _sol({'mon': {'rice__1': 'a'}, 'tue': {'rice__1': 'b'}})
        dinner = _sol({'mon': {'rice__1': 'z'}})
        out = meal_difference(lunch, dinner)
        assert list(out['per_day']) == ['mon']

    def test_empty_input_is_zero_not_a_crash(self):
        assert meal_difference({}, {})['overall'] == 0.0
        assert meal_difference(None, None)['below_floor'] == []


# ---------------------------------------------------------------------------
# The planner's own two-meal helpers. `app.py` is a Streamlit script and cannot
# be imported without a running session, so the two pure functions are read out
# of its AST and executed against the same namespace they use. That is uglier
# than an import and it is the only way to test them where they live — moving
# them into `ui/` to make them importable would put planner control flow in the
# formatter module, which is worse.
# ---------------------------------------------------------------------------

import ast as _ast
import pathlib as _pathlib

from src.history import DINNER, LUNCH
from ui.formatters import dishes_from_solution as _dishes_from_solution


def _planner_helpers():
    src = (_pathlib.Path(__file__).resolve().parents[2] / 'app.py').read_text()
    tree = _ast.parse(src)
    wanted = {'_exclusions_from', '_saveable_meals', '_concat_meal_blocks',
              '_merge_exclusions'}
    ns = {'dishes_from_solution': _dishes_from_solution,
          'LUNCH': LUNCH, 'DINNER': DINNER}
    found = [n for n in tree.body
             if isinstance(n, _ast.FunctionDef) and n.name in wanted]
    assert {n.name for n in found} == wanted, (
        'app.py no longer defines both helpers at module level; this test '
        'cannot reach them and is measuring nothing')
    exec(compile(_ast.Module(body=found, type_ignores=[]), 'app.py', 'exec'), ns)
    return (ns['_exclusions_from'], ns['_saveable_meals'],
            ns['_concat_meal_blocks'], ns['_merge_exclusions'])


(_exclusions_from, _saveable_meals, _concat_meal_blocks,
 _merge_exclusions) = _planner_helpers()


def _block(name, solution, plan=None):
    return {'name': name, 'solution': solution, 'plan': plan or {'d': {}},
            'plan_dates': ['2026-03-02']}


class TestWhatDinnerIsToldToAvoid:
    LUNCH_SOL = {
        '2026-03-02': {'items': {'veg_gravy__1': {'item_base': 'dal_tadka'},
                                 'bread__1': {'item_base': 'plain_chapati'}}},
        '2026-03-03': {'items': {'veg_gravy__1': {'item_base': 'paneer_butter_masala'}}},
    }

    def test_every_lunch_dish_is_banned_on_every_day(self):
        """Not just its own day.

        `unique_items` is scoped to ONE solve, so nothing else stops Monday's
        lunch dal turning up at Wednesday's dinner inside a single generation.
        The cooldown catches it only once the plan is saved, which is after it
        is on screen.
        """
        out = _exclusions_from([_block('C1', self.LUNCH_SOL)])
        assert set(out) == {0}
        for day, items in out[0].items():
            assert set(items) == {'dal_tadka', 'plain_chapati',
                                  'paneer_butter_masala'}, day

    def test_counters_are_kept_apart(self):
        """Keyed per counter, not pooled across the site.

        Pooling a six-counter site's lunch would ban eighty dishes from every
        dinner cell and starve the thin pools, for a collision between two
        separate stations that no diner is standing in front of.
        """
        other = {'2026-03-02': {'items': {'rice__1': {'item_base': 'jeera_rice'}}}}
        out = _exclusions_from([_block('C1', self.LUNCH_SOL), _block('C2', other)])
        assert 'jeera_rice' not in out[0]['2026-03-02']
        assert out[1]['2026-03-02'] == ['jeera_rice']

    def test_a_counter_that_failed_contributes_nothing(self):
        """A block with no solution must not key an empty exclusion.

        `{}` and "no entry" mean the same thing to the caller, but an empty
        dict sent as `exclude_items` is a payload key with nothing in it —
        noise in the request and in the log.
        """
        out = _exclusions_from([{'name': 'C1', 'source': 'error'},
                                _block('C2', self.LUNCH_SOL)])
        assert set(out) == {1}


class TestWhichServicesGetSaved:
    def test_both_meals_are_returned(self):
        """An unsaved dinner is not a missing row the next plan can notice.

        `menu_history` is keyed on (client, date, meal), so a dinner that is
        never written is a menu the cooldown and the freshness objective have
        never heard of — and the following week reprints it.
        """
        mb = {LUNCH: [_block('C1', {})], DINNER: [_block('C1', {})]}
        got = _saveable_meals(mb, [])
        assert [m for m, _ in got] == sorted([LUNCH, DINNER])

    def test_a_service_with_no_blocks_is_skipped(self):
        mb = {LUNCH: [_block('C1', {})], DINNER: []}
        assert [m for m, _ in _saveable_meals(mb, [])] == [LUNCH]

    def test_it_falls_back_to_lunch_for_a_pre_feature_plan(self):
        """The shape a saved-plan REPLAY produces, and the shape any plan
        generated before this feature existed has in session state. Saving it
        as lunch is right: that is what every history row predating the column
        is."""
        blocks = [_block('C1', {})]
        assert _saveable_meals({}, blocks) == [(LUNCH, blocks)]

    def test_nothing_to_save_is_an_empty_list_not_a_crash(self):
        assert _saveable_meals({}, []) == []


class TestWhereEachServicesBlocksLand:
    """The offset arithmetic behind the stacked layout.

    Dinner renders as a section BELOW lunch, and both sections address one
    concatenated `plan_blocks` list. An offset wrong by one points the dinner
    section's Regenerate at a LUNCH cell — silently, because both are real
    blocks and the page still renders perfectly.
    """

    def test_lunch_comes_first_and_dinner_follows_it(self):
        mb = {LUNCH: [_block('A', {}), _block('B', {})],
              DINNER: [_block('A', {}), _block('B', {})]}
        blocks, offsets = _concat_meal_blocks([LUNCH, DINNER], mb)
        assert len(blocks) == 4
        assert offsets == {LUNCH: 0, DINNER: 2}
        for meal in (LUNCH, DINNER):
            for i, b in enumerate(mb[meal]):
                assert blocks[offsets[meal] + i] is b

    def test_the_blocks_are_the_same_objects_not_copies(self):
        """A regenerate mutates `plan_blocks[i]` in place. If the
        concatenation copied, the edit would vanish on the next rerun when the
        page rebuilds the list from `meal_blocks`."""
        mb = {LUNCH: [_block('A', {})], DINNER: [_block('A', {})]}
        blocks, offsets = _concat_meal_blocks([LUNCH, DINNER], mb)
        blocks[offsets[DINNER]]['plan'] = {'edited': {}}
        assert mb[DINNER][0]['plan'] == {'edited': {}}
        assert mb[LUNCH][0]['plan'] != {'edited': {}}

    def test_one_service_is_unchanged(self):
        mb = {LUNCH: [_block('A', {}), _block('B', {})]}
        blocks, offsets = _concat_meal_blocks([LUNCH], mb)
        assert len(blocks) == 2 and offsets == {LUNCH: 0}

    def test_a_service_with_no_blocks_still_gets_an_offset(self):
        """A failed dinner renders its own warning and must not shift the
        offsets of anything after it, nor raise on lookup."""
        mb = {LUNCH: [_block('A', {})], DINNER: []}
        blocks, offsets = _concat_meal_blocks([LUNCH, DINNER], mb)
        assert len(blocks) == 1
        assert offsets == {LUNCH: 0, DINNER: 1}

    def test_nothing_at_all(self):
        assert _concat_meal_blocks([], {}) == ([], {})


# ---------------------------------------------------------------------------
# Four services, not two.
# ---------------------------------------------------------------------------

from src.history import BREAKFAST, SNACKS, MEALS, DEFAULT_MEALS, normalize_meals  # noqa: E402


class TestTheMealList:
    def test_the_order_is_when_they_are_eaten(self):
        """Not the order anyone lists them in. Snacks sit between lunch and
        dinner because that is when a canteen serves them, and this order IS
        the solve order — each service avoids the ones before it."""
        assert MEALS == (BREAKFAST, LUNCH, SNACKS, DINNER)

    def test_every_client_defaults_to_lunch_and_dinner(self):
        assert list(DEFAULT_MEALS) == [LUNCH, DINNER]
        assert normalize_meals(None) == [LUNCH, DINNER]

    def test_the_caller_cannot_change_the_order(self):
        """Ticking boxes in a different order must not reorder the solve."""
        assert normalize_meals([DINNER, BREAKFAST, LUNCH]) == [
            BREAKFAST, LUNCH, DINNER]

    def test_nothing_selected_reads_as_the_default(self):
        """A client that serves NO meal cannot be planned, and returning an
        empty list would surface as a solver failure rather than a config
        mistake."""
        assert normalize_meals([]) == list(DEFAULT_MEALS)
        assert normalize_meals(['not_a_meal']) == list(DEFAULT_MEALS)

    def test_duplicates_and_case_collapse(self):
        assert normalize_meals(['LUNCH', 'lunch', ' Lunch ']) == [LUNCH]


class TestExclusionsAccumulate:
    """Dinner must avoid breakfast AND lunch AND snacks — not merely the
    service immediately before it. Passing only the previous one fails
    quietly: the menu still renders, it just reprints the morning's dishes at
    night."""

    def test_two_services_union_per_counter_and_day(self):
        a = {0: {'2026-03-02': ['idli', 'chutney']}}
        b = {0: {'2026-03-02': ['dal', 'idli']}}
        assert _merge_exclusions(a, b) == {
            0: {'2026-03-02': ['chutney', 'dal', 'idli']}}

    def test_counters_stay_separate(self):
        a = {0: {'d': ['x']}}
        b = {1: {'d': ['y']}}
        out = _merge_exclusions(a, b)
        assert out == {0: {'d': ['x']}, 1: {'d': ['y']}}

    def test_a_new_day_is_added_not_dropped(self):
        a = {0: {'d1': ['x']}}
        b = {0: {'d2': ['y']}}
        assert _merge_exclusions(a, b) == {0: {'d1': ['x'], 'd2': ['y']}}

    def test_it_does_not_mutate_what_it_was_given(self):
        """The loop reassigns the accumulator each round; mutating in place
        would make an earlier service's exclusions grow retroactively."""
        a = {0: {'d': ['x']}}
        _merge_exclusions(a, {0: {'d': ['y']}})
        assert a == {0: {'d': ['x']}}

    def test_empty_inputs(self):
        assert _merge_exclusions({}, {}) == {}
        assert _merge_exclusions(None, {0: {'d': ['x']}}) == {0: {'d': ['x']}}
        assert _merge_exclusions({0: {'d': ['x']}}, None) == {0: {'d': ['x']}}
