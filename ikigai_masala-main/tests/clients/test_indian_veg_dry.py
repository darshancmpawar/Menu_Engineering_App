"""`indian_veg_dry_themes` — the veg dry stays Indian on a themed day.

A continental day already works this way unconditionally: the continental veg is
the *gravy*, and the veg_dry beside it stays a normal Indian dish, so the plate
reads as one cuisine plus a familiar side rather than two foreign dishes.
Tekion, Stryker and Stripe want the same on their Chinese day — the veg dry
should be north or south Indian, whichever suits the rest of that day's menu.

This is a config key rather than a global change because it is a client
preference: a counter that wants gobi manchurian beside its Chinese fried rice
is equally valid, and every ruleset that omits the key behaves exactly as before.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from src.menu_rules.theme_rules import ThemeSlotFilterRule

DAY = dt.date(2026, 8, 25)          # a Tuesday — chinese under the default map


def _pool():
    """A veg_dry pool with both Chinese and Indian dishes, plus a Chinese dish
    the text heuristic would catch by name (`gobi_manchurian`) and an Indian one
    it would wrongly catch (`chilli_paneer_dry` contains 'chilli')."""
    return pd.DataFrame([
        {'item': 'gobi_manchurian', 'cuisine_family': 'chinese',
         'sub_category': 'chinese_dry', 'is_chinese_veg_dry': 1},
        {'item': 'schezwan_veg', 'cuisine_family': 'chinese',
         'sub_category': 'chinese_dry', 'is_chinese_veg_dry': 1},
        {'item': 'aloo_jeera', 'cuisine_family': 'north_indian',
         'sub_category': 'north_dry', 'is_chinese_veg_dry': 0},
        {'item': 'beans_poriyal', 'cuisine_family': 'south_indian',
         'sub_category': 'south_dry', 'is_chinese_veg_dry': 0},
        {'item': 'garlic_bread_bites', 'cuisine_family': 'continental',
         'sub_category': 'continental_dry', 'is_chinese_veg_dry': 0},
    ])


def _rule(**cfg):
    base = {'type': 'theme_slot_filter', 'name': 'theme_cuisine_filter'}
    base.update(cfg)
    return ThemeSlotFilterRule(base)


def _names(df):
    return set(df['item'].astype(str))


def _filter(rule, base_slot='veg_dry', day_type='chinese', pool=None):
    return rule.pre_filter_pool(
        (_pool() if pool is None else pool).copy(), DAY, base_slot, day_type,
        {'cfg': None},
    )


def test_default_behaviour_is_unchanged():
    """No key => the Chinese day still gets a Chinese veg dry."""
    out = _names(_filter(_rule()))
    assert 'gobi_manchurian' in out
    assert 'aloo_jeera' not in out, 'an Indian dish leaked into an unconfigured rule'


def test_declared_theme_keeps_the_veg_dry_indian():
    out = _names(_filter(_rule(indian_veg_dry_themes=['chinese'])))
    assert out == {'aloo_jeera', 'beans_poriyal'}, out


def test_both_regions_are_offered_so_the_solver_picks():
    """'north or south, whichever best suits that day' — so keep both rather
    than pinning a region and deciding for the menu."""
    out = _names(_filter(_rule(indian_veg_dry_themes=['chinese'])))
    assert 'aloo_jeera' in out and 'beans_poriyal' in out


def test_continental_is_still_excluded_from_veg_dry():
    out = _names(_filter(_rule(indian_veg_dry_themes=['chinese'])))
    assert 'garlic_bread_bites' not in out


def test_other_slots_on_the_chinese_day_are_untouched():
    """Only veg_dry changes — the rice/gravy/starter/nonveg stay Chinese."""
    pool = pd.DataFrame([
        {'item': 'veg_fried_rice', 'cuisine_family': 'chinese',
         'is_chinese_fried_rice': 1},
        {'item': 'jeera_rice', 'cuisine_family': 'north_indian',
         'is_chinese_fried_rice': 0},
    ])
    out = _names(_filter(_rule(indian_veg_dry_themes=['chinese']),
                         base_slot='rice', pool=pool))
    assert out == {'veg_fried_rice'}, out


@pytest.mark.parametrize('day_type', ['south', 'north', 'biryani', 'mix'])
def test_other_theme_days_are_untouched(day_type):
    """The key names ONE theme; a south day still gets a south veg dry."""
    rule = _rule(indian_veg_dry_themes=['chinese'])
    plain = _rule()
    assert _names(_filter(rule, day_type=day_type)) == \
        _names(_filter(plain, day_type=day_type))


def test_falls_back_rather_than_emptying_the_slot():
    """An all-Chinese pool would leave nothing Indian; the slot must not empty."""
    pool = pd.DataFrame([
        {'item': 'gobi_manchurian', 'cuisine_family': 'chinese',
         'is_chinese_veg_dry': 1},
        {'item': 'schezwan_veg', 'cuisine_family': 'chinese',
         'is_chinese_veg_dry': 1},
    ])
    out = _filter(_rule(indian_veg_dry_themes=['chinese']), pool=pool)
    assert len(out) > 0, 'the veg_dry slot was emptied'


def test_diagnose_projection_matches_the_filter():
    """`_project_filter_size` must model the same branch.

    It drives the pre-flight report, and projecting the Chinese heuristic here
    would raise a phantom "0 items match the chinese filter" WARNING for a slot
    the solver never filters that way — the divergence that bit the bread
    exemption before.
    """
    rule = _rule(indian_veg_dry_themes=['chinese'])
    projected = rule._project_filter_size(
        _pool(), 'veg_dry', 'chinese', 'cuisine_family',
        'south_indian', 'north_indian',
    )
    assert projected == len(_filter(rule))
