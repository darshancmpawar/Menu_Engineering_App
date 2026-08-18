"""Tests for the curd-family categories (F1).

Covers: the plain-curd station pool (is_plain_curd flag), its repeatability
exemptions being registered, the Curd/Raita relabel, and the mutual-exclusion
validation between plain curd and curd/raita.
"""

import pandas as pd
import pytest

import datetime as dt

from src.constants import (
    BASE_SLOT_NAMES, DEFAULT_OFF_SLOTS, REPEATABLE_SLOTS, DISPLAY_SLOT_NAME,
    MUTUALLY_EXCLUSIVE_SLOT_GROUPS, COOLDOWN_EXEMPT_SLOTS,
)
from src.menu_rules.cooldown_rules import ItemCooldownMenuRule
from src.preprocessor.pool_builder import PoolBuilder


def _ontology():
    rows = []
    for slot in ['welcome_drink', 'soup', 'salad', 'starter', 'bread', 'rice',
                 'healthy_rice', 'dal', 'veg_gravy', 'veg_dry', 'nonveg_main',
                 'curd_side', 'dessert']:
        rows.append({'item': f'{slot}_1', 'course_type': slot,
                     'cuisine_family': 'indian', 'item_color': 'red'})
        rows.append({'item': f'{slot}_2', 'course_type': slot,
                     'cuisine_family': 'indian', 'item_color': 'green'})
    rows.append({'item': 'sambar dal', 'course_type': 'sambar',
                 'cuisine_family': 'south_indian', 'item_color': 'yellow'})
    rows.append({'item': 'tomato rasam', 'course_type': 'rasam',
                 'cuisine_family': 'south_indian', 'item_color': 'orange'})
    return pd.DataFrame(rows)


class TestCurdCategoryRegistration:
    def test_curd_slot_selectable_off_by_default_and_repeatable(self):
        assert 'curd' in BASE_SLOT_NAMES
        assert 'curd' in DEFAULT_OFF_SLOTS       # selectable, off by default
        assert 'curd' in REPEATABLE_SLOTS        # repeats freely

    def test_display_labels(self):
        assert DISPLAY_SLOT_NAME['curd'] == 'Curd'
        assert DISPLAY_SLOT_NAME['curd_side'] == 'Curd / Raita'  # relabeled

    def test_curd_curd_raita_are_a_mutex_group(self):
        assert frozenset({'curd', 'curd_side'}) in MUTUALLY_EXCLUSIVE_SLOT_GROUPS


class TestCurdSideCurdRiceCooldownExempt:
    """curd_side (Curd/Raita) and curd_rice are exempt from the 20-day item
    cooldown ban so their small pools are never drained empty by it — but,
    unlike REPEATABLE_SLOTS, they KEEP unique_items, so they still vary within
    a week and only repeat once every distinct dish has been used.
    """

    def test_slots_are_cooldown_exempt_but_not_repeatable(self):
        # These repeat only after a full cycle: the cooldown never bans them, but
        # `unique_items` still makes them distinct within a week.
        for slot in ('curd_side', 'soup', 'healthy_rice'):
            assert slot in COOLDOWN_EXEMPT_SLOTS      # cooldown never bans them
            assert slot not in REPEATABLE_SLOTS       # unique_items still applies

    def test_curd_and_curd_rice_are_staples(self):
        """Curd rice is a staple the way steamed rice is — the same bowl every
        day is what the station serves, not a variety slot. So it is exempt from
        `unique_items` too, not just the cooldown."""
        for slot in ('curd', 'curd_rice'):
            assert slot in REPEATABLE_SLOTS, slot

    def _banned_ctx(self, d, items):
        return {'banned_by_date': {d: set(items)}, 'extra_repeatable': {}}

    def test_cooldown_never_empties_curd_side_or_curd_rice(self):
        """Even when every candidate was served inside the window, the exempt
        slots keep their full pool; a normal slot is emptied."""
        rule = ItemCooldownMenuRule(
            {'type': 'item_cooldown', 'name': 'item_cooldown_20d',
             'cooldown_days': 20})
        d = dt.date(2026, 8, 24)
        pool = pd.DataFrame({'item': ['a', 'b', 'c']})
        ctx = self._banned_ctx(d, ['a', 'b', 'c'])   # all three cooling down

        for slot in ('curd_side', 'curd_rice', 'soup', 'healthy_rice'):
            out = rule.pre_filter_pool(pool, d, slot, 'north', ctx)
            assert list(out['item']) == ['a', 'b', 'c'], (
                f'{slot} pool should survive the cooldown intact')

    def test_ordinary_slot_is_still_cooled_down_strictly(self):
        """Repetition is hard everywhere except the declared slots: a non-exempt
        slot loses every cooled-down dish, even if that empties it (the fix for
        an empty pool is more dishes, not a repeat)."""
        rule = ItemCooldownMenuRule(
            {'type': 'item_cooldown', 'name': 'item_cooldown_20d',
             'cooldown_days': 20})
        d = dt.date(2026, 8, 24)
        pool = pd.DataFrame({'item': ['a', 'b', 'c']})
        ctx = {'banned_by_date': {d: {'a', 'b', 'c'}}, 'extra_repeatable': {}}
        assert len(rule.pre_filter_pool(pool, d, 'veg_gravy', 'north', ctx)) == 0

        ctx2 = {'banned_by_date': {d: {'a'}}, 'extra_repeatable': {}}
        out2 = rule.pre_filter_pool(pool, d, 'veg_gravy', 'north', ctx2)
        assert set(out2['item']) == {'b', 'c'}


class TestCurdPool:
    def test_curd_pool_from_is_plain_curd_flag(self):
        df = _ontology()
        df['is_plain_curd'] = 0
        df.loc[df['course_type'] == 'curd_side', 'is_plain_curd'] = 1
        pools = PoolBuilder.build_pools(df)
        expected = set(df.loc[df['is_plain_curd'] == 1, 'item'])
        assert expected and set(pools['curd']['item']) == expected

    def test_curd_pool_empty_without_flag(self):
        # curd is default-off, so an ontology with no is_plain_curd column
        # yields an empty (but present) pool — not a build failure.
        pools = PoolBuilder.build_pools(_ontology())
        assert 'curd' in pools and len(pools['curd']) == 0


class TestCurdMutualExclusion:
    def _validate(self, cats):
        from src.client.client_config import ClientConfigLoader
        ClientConfigLoader._validate_counters(
            [{'name': 'C1', 'categories': cats}]
        )

    def test_curd_and_curd_raita_together_rejected(self):
        with pytest.raises(ValueError, match="mutually exclusive"):
            self._validate(['rice', 'curd', 'curd_side'])

    def test_curd_plus_curd_rice_allowed(self):
        self._validate(['rice', 'curd', 'curd_rice'])  # must not raise

    def test_curd_raita_plus_curd_rice_allowed(self):
        self._validate(['rice', 'curd_side', 'curd_rice'])  # must not raise
