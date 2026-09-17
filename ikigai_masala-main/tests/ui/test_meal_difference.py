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
