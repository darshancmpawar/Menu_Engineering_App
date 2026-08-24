"""A pinned dish may be a FIXED ITEM the counter serves without a station.

A daily curd, papad or welcome drink is served every day and never chosen. It
does not need a rotating category — but `constant_items` used to require one, and
a pin naming a slot the counter did not serve vanished silently. Six clients were
losing a stated fixed item this way.

Two separate bugs had to be fixed to make one pin land, which is why both are
pinned here:

1. **The pin was dropped** by `_resolve_constant_items`. That guard is right for a
   multi-counter client — `constant_items` is client-scoped, so a pin meant for
   the main counter must not grow a row on a two-slot Chinese station — but with
   ONE counter there is no sibling station and the pin is unambiguous.

2. **The pin was then swallowed by the forcing path.** `pools` holds every slot
   the ontology can fill, not the ones the counter serves, so a surviving pin
   resolved to a real dish and went into `forced_items`. The solver has no cell
   to narrow, and the post-solve stamp skips anything in `forced_items` on the
   grounds that the solver placed it — so the row disappeared through both
   paths with nothing logged. Booking.com's daily curd was exactly this: its pin
   survived (the `curd_side` sibling is served) and Bangalore has a real `curd`
   dish for it to match, which is what put it on the forcing path.
"""

from __future__ import annotations

import pytest

from src.application.constant_items import _resolve_constant_items


class _Cfg:
    """The parts of `ClientConfig` the resolver reads."""

    def __init__(self, active_slots, counter_count=1, name='Counter 1'):
        self.active_slots = list(active_slots)
        self.counter_count = counter_count
        self.name = name


class TestASoleCounterKeepsThePin:
    def test_a_pin_for_an_unserved_slot_survives_on_a_one_counter_client(self):
        resolved, whole = _resolve_constant_items(
            'Solo', {'curd': 'Curd'}, _Cfg(['rice', 'dal']))
        assert resolved == {'curd': 'Curd'}
        # NOT in `whole_slot_bases`: that set exists to drop a base slot from
        # the model, and this slot was never in it. Adding it would be a no-op
        # that reads as though a cell had been suppressed.
        assert whole == set()

    def test_a_weekday_map_survives_too(self):
        resolved, _ = _resolve_constant_items(
            'Solo', {'curd_side': {'wednesday': 'raita'}}, _Cfg(['rice']))
        assert resolved == {'curd_side': {'wednesday': 'raita'}}

    def test_a_multi_counter_client_still_drops_it(self):
        """The guard's real purpose: a pin meant for the main counter must not
        grow a row on a sibling station that does not serve the slot."""
        resolved, _ = _resolve_constant_items(
            'Multi', {'salad': 'Green Salad'},
            _Cfg(['rice', 'veg_gravy'], counter_count=3))
        assert resolved == {}

    def test_the_exclusive_sibling_exception_is_unchanged(self):
        """`curd`/`curd_side` are one logical yogurt slot, so a pin across the
        pair is kept even on a multi-counter client."""
        resolved, _ = _resolve_constant_items(
            'Multi', {'curd': 'Curd'},
            _Cfg(['curd_side', 'rice'], counter_count=4))
        assert resolved == {'curd': 'Curd'}

    def test_an_unknown_slot_is_still_refused(self):
        """Widening the served-slot check must not widen the registry check —
        an ad-hoc key has no display label and no rank in DISPLAY_SLOT_ORDER."""
        resolved, _ = _resolve_constant_items(
            'Solo', {'not_a_slot': 'Something'}, _Cfg(['rice']))
        assert resolved == {}

    def test_a_served_slot_is_unaffected(self):
        resolved, _ = _resolve_constant_items(
            'Solo', {'rice': 'Jeera Rice'}, _Cfg(['rice', 'dal']))
        assert resolved == {'rice': 'Jeera Rice'}


class TestTheStampWinsWhenThereIsNoCell:
    """Bug 2, through the real function.

    ``_rules_and_skip_for_client`` decides force-vs-stamp. It is given `pools`,
    which holds every slot the ONTOLOGY can fill — not the ones this counter
    serves — so before the fix a pin for an unserved slot matched a real dish and
    went into ``forced_items``, where the post-solve stamp then skipped it as
    "already placed". Nothing rendered.
    """

    @staticmethod
    def _pools():
        pd = pytest.importorskip('pandas')
        return {
            'curd': pd.DataFrame({'item': ['curd', 'sweet_curd']}),
            'rice': pd.DataFrame({'item': ['jeera_rice', 'ghee_rice']}),
        }

    def _run(self, pins, active, counter_count=1):
        import datetime as dt
        from api.app import _rules_and_skip_for_client
        from src.menu_rules.menu_rule_loader import MenuRuleLoader

        cfg = _Cfg(active, counter_count=counter_count)
        dates = [dt.date(2026, 9, 7)]
        real = MenuRuleLoader.get_client_constant_items
        try:
            MenuRuleLoader.get_client_constant_items = (
                lambda self, name, counter=None: dict(pins))
            _rules, _skip, constants, _whole, forced = (
                _rules_and_skip_for_client(
                    'Solo', dates, city='Bangalore', client_cfg=cfg,
                    pools=self._pools()))
        finally:
            MenuRuleLoader.get_client_constant_items = real
        return constants, forced

    def test_an_unserved_slot_is_stamped_not_forced(self):
        """`curd` has a pool and a matching dish, so the old code forced it —
        onto a cell that does not exist."""
        constants, forced = self._run({'curd': 'Curd'}, ['rice'])
        assert 'curd' in constants, "the pin must survive to be stamped"
        assert not [k for k in forced if k[1] == 'curd'], forced

    def test_a_served_slot_is_still_forced(self):
        """The counter-case: forcing is how a pin stays visible to every other
        rule, so it must not have been broken for the slots that have a cell.

        A weekday MAP, not a bare string: a bare string replaces the slot for the
        whole horizon and is stamped by design (`whole_slot_bases`), so it would
        not distinguish the fix from the bug.
        """
        constants, forced = self._run(
            {'rice': {'monday': 'Jeera Rice'}}, ['rice'])
        assert 'rice' in constants
        assert [v for k, v in forced.items() if k[1] == 'rice'] == ['jeera_rice']

    def test_a_pin_naming_no_real_dish_is_stamped_either_way(self):
        constants, forced = self._run(
            {'rice': {'monday': 'Mutton Biryani'}}, ['rice'])
        assert 'rice' in constants
        assert not [k for k in forced if k[1] == 'rice'], forced

    def test_a_whole_slot_string_is_stamped_even_on_a_served_slot(self):
        """Pre-existing behaviour, pinned so the fix above is not confused with
        it: a bare string drops the base slot from the model, so there is no cell
        to narrow whatever the dish is. See docs/pending_config_changes.md."""
        constants, forced = self._run({'rice': 'Jeera Rice'}, ['rice'])
        assert 'rice' in constants
        assert not [k for k in forced if k[1] == 'rice'], forced
