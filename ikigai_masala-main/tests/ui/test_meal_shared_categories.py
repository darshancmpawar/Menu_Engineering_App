"""Slots a later service repeats from the first, instead of avoiding.

Corning Chakan: "dessert, soup and indian bread shall be the same as Lunch."

This is the exact opposite of what the planner does by default. Note 39's
arrangement bans every lunch dish at dinner — and bans it on every DAY of the
horizon, not just its own — so without this the three slots the client wants
identical are the three the planner works hardest to keep apart.

It cannot be a solver rule. Lunch and dinner are separate CP-SAT models;
`unique_items` is scoped to one of them and the cooldown reads only SAVED
history, which is after the menu is on screen. So the carry-over is the
caller's job, the way the cross-counter sync already is — this is that same
mechanism one axis over: `shared_categories` carries the primary COUNTER's
dish to the other counters of one service, `meal_shared_categories` carries
the first SERVICE's dish to the same counter at the next sitting.

The failure mode worth a test of its own: pinning a dish that is ALSO banned.
`merge_shared_items` narrows the cell to the pinned dish and the exclusion
goes into `banned_by_date`, so doing both leaves the cell with no candidate
and the day goes infeasible — a pin and a ban are one decision and have to be
made in one place.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from ui.formatters import dishes_from_solution, shared_items_from_solution

CLIENT_RULES = (pathlib.Path(__file__).resolve().parents[2]
                / 'customisation' / 'client rules')


def _sol(by_date):
    return {d: {'items': {s: {'item_base': i} for s, i in slots.items()}}
            for d, slots in by_date.items()}


LUNCH = _sol({
    '2026-11-02': {'dessert': 'gajar_halwa', 'soup__1': 'tomato_soup',
                   'bread': 'chapati', 'rice': 'jeera_rice',
                   'veg_gravy': 'paneer_butter_masala'},
    '2026-11-03': {'dessert': 'rasmalai', 'soup__1': 'sweet_corn_soup',
                   'bread': 'chapati', 'rice': 'ghee_rice',
                   'veg_gravy': 'aloo_matar'},
})
SHARED = ['dessert', 'soup', 'bread']


class TestTheSharedSlotsAreCarriedNotBanned:
    def test_the_shared_dishes_are_left_out_of_the_ban(self):
        """The half that is easy to forget, because the menu still renders
        without it: dinner would be pinned to lunch's halwa and banned from
        serving it on the same day."""
        banned = dishes_from_solution(LUNCH, keep_slots=SHARED)
        flat = {i for day in banned.values() for i in day}
        assert 'gajar_halwa' not in flat
        assert 'tomato_soup' not in flat
        assert 'chapati' not in flat

    def test_everything_else_is_still_banned(self):
        """The default has to survive. Only the named slots are carried."""
        banned = dishes_from_solution(LUNCH, keep_slots=SHARED)
        flat = {i for day in banned.values() for i in day}
        assert {'jeera_rice', 'ghee_rice', 'paneer_butter_masala',
                'aloo_matar'} <= flat

    def test_and_the_ban_is_unchanged_for_a_client_that_names_none(self):
        assert (dishes_from_solution(LUNCH, keep_slots=[])
                == dishes_from_solution(LUNCH))

    def test_the_carried_pins_name_the_day_and_the_cell(self):
        """A pin is `[date, slot_id, item]` and the slot id keeps its index,
        so a two-soup counter pins soup 1 to soup 1 rather than to the slot
        family."""
        pins = shared_items_from_solution(LUNCH, SHARED)
        assert ['2026-11-02', 'soup__1', 'tomato_soup'] in pins
        assert ['2026-11-03', 'dessert', 'rasmalai'] in pins
        assert not [p for p in pins if p[1] in ('rice', 'veg_gravy')]

    def test_a_pin_and_a_ban_never_name_the_same_dish(self):
        """The two halves read the same list, so they cannot disagree — which
        is the point. A cell narrowed to a pinned dish that is also in
        `banned_by_date` has no candidate at all and takes the day down."""
        pinned = {p[2] for p in shared_items_from_solution(LUNCH, SHARED)}
        banned = {i for day in dishes_from_solution(
            LUNCH, keep_slots=SHARED).values() for i in day}
        assert not (pinned & banned)


class TestTheConfigReachesThePlanner:
    def test_corning_chakan_names_the_three_slots(self):
        blob = json.loads((CLIENT_RULES / 'corning_chakan.json').read_text())
        assert blob['Corning Chakan']['meal_shared_categories'] == [
            'dessert', 'soup', 'bread']

    def test_the_loader_reads_it(self):
        from src.menu_rules.menu_rule_loader import MenuRuleLoader
        assert MenuRuleLoader().get_meal_shared_categories(
            'Corning Chakan') == ['dessert', 'soup', 'bread']

    def test_a_client_that_says_nothing_gets_an_empty_list(self):
        """Opt-in. Every other client keeps the default, which is that dinner
        may not reprint lunch at all."""
        from src.menu_rules.menu_rule_loader import MenuRuleLoader
        assert MenuRuleLoader().get_meal_shared_categories('Amadeus') == []

    def test_the_client_config_endpoint_serves_it(self, fake_supabase):
        """The planner reads it beside `shared_categories` in the same call —
        a file-only key with no DB column and no editor control, so the
        endpoint is the only way it reaches the UI."""
        from api.app import app
        from tests.client_fixtures import CLIENTS
        fake_supabase.seed('clients', [dict(next(
            c for c in CLIENTS if c['name'] == 'Corning Chakan'))])
        app.config['TESTING'] = True
        with app.test_client() as c:
            resp = c.get('/api/v1/client-config/Corning%20Chakan')
        assert resp.status_code == 200, resp.get_json()
        assert resp.get_json()['meal_shared_categories'] == [
            'dessert', 'soup', 'bread']


class TestThePlannerWiresBothHalves:
    """Read off `app.py` itself. These two lines are the whole feature and
    each is a single argument that can be dropped without anything failing —
    drop the pin and dinner simply varies, drop the `keep_slots` and the
    pinned cell has nothing to take."""

    @staticmethod
    def _src():
        return (pathlib.Path(__file__).resolve().parents[2]
                / 'app.py').read_text()

    def test_the_ban_is_told_which_slots_to_skip(self):
        assert '_exclusions_from(blocks, keep_slots=meal_shared)' in self._src()

    def test_the_pins_are_taken_from_the_first_service_only(self):
        """"The same as Lunch" means lunch, not "the same as whatever came
        before" — a three-service client's snacks must not reset the carry."""
        src = self._src()
        i = src.index('carried_over = _meal_shared_from(blocks, meal_shared)')
        assert 'if _i == 0:' in src[i - 200:i]

    def test_the_pins_are_passed_to_the_later_service(self):
        assert 'meal_shared_by_counter=carried_over or None' in self._src()


def test_a_real_lunch_and_dinner_for_corning_chakan(fake_supabase):
    """Both services solved and sequenced the way the planner sequences them.

    Every unit above can pass while the feature does nothing: the two halves
    are single arguments at one call site, and the menu renders either way.
    This is the only check that fails if the wiring is dropped — and it
    asserts BOTH directions, because a carry-over that also stopped rice and
    gravy varying would satisfy the client's sentence and ruin the menu.
    """
    from api.app import app
    from tests.client_fixtures import CLIENTS
    from api.rate_limit import reset_for_tests

    fake_supabase.seed('clients', [dict(next(
        c for c in CLIENTS if c['name'] == 'Corning Chakan'))])
    app.config['TESTING'] = True

    def plan(meal, **extra):
        reset_for_tests()
        with app.test_client() as c:
            resp = c.post('/api/v1/plan', json={
                'client_name': 'Corning Chakan', 'start_date': '2026-11-02',
                'num_days': 7, 'time_limit_seconds': 40, 'meal': meal, **extra})
        body = resp.get_json() or {}
        assert resp.status_code == 200, (meal, body.get('error')
                                         or body.get('message'))
        return body['solution']

    lunch = plan('lunch')
    dinner = plan('dinner',
                  shared_items=shared_items_from_solution(lunch, SHARED),
                  exclude_items=dishes_from_solution(lunch, keep_slots=SHARED))

    def served(sol, iso, base):
        return {v['item_base'] for s, v in sol[iso]['items'].items()
                if s.split('__')[0] == base}

    same = different = 0
    for iso in lunch:
        for base in SHARED:
            if served(lunch, iso, base):
                assert served(lunch, iso, base) == served(dinner, iso, base), (
                    f'{iso} {base}: dinner did not repeat lunch')
                same += 1
        for base in ('rice', 'veg_gravy'):
            if served(lunch, iso, base) and served(dinner, iso, base):
                assert served(lunch, iso, base) != served(dinner, iso, base), (
                    f'{iso} {base}: dinner reprinted lunch and should not')
                different += 1
    assert same >= 7 and different >= 7, (same, different)


if __name__ == '__main__':      # a runnable check without pytest
    raise SystemExit(pytest.main([__file__, '-q']))
