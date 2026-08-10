"""Desserts carry their real regional origin, not the import's `north_indian`
default.

`cuisine_family` feeds the theme filter. Desserts are theme-exempt today, so this
is a correctness fix against a future landmine (D1 in
docs/data_fixes_for_client.md): the moment desserts are themed, a South Indian day
whose payasams and kesaris are all tagged `north_indian` loses its dessert pool.
These pin the reassignment and — just as important — the two families deliberately
left in `north_indian` because the vocabulary has no East/West bucket.
"""

from __future__ import annotations

import os

import pandas as pd
import pytest

from scripts.dessert_cuisine_corrections import (
    CITY_ITEMS,
    apply_dessert_cuisine,
    classify,
)

CITIES = ['bangalore', 'chennai', 'pune']


def _read(city):
    return pd.read_excel(os.path.join(CITY_ITEMS, f'{city}.xlsx'))


@pytest.mark.parametrize('city', CITIES)
def test_rerunning_the_correction_changes_nothing(city):
    _after, changes = apply_dessert_cuisine(_read(city))
    assert not changes, changes


def test_the_headline_south_indian_sweets_are_south():
    """The dishes the client named — kesaris and payasams — plus the mysore pak /
    holige / sweet-pongal families."""
    d = _read('bangalore').set_index('item')
    for item in ('mysore_pak', 'kesari_bath', 'payasam', 'pal_payasam',
                 'holige', 'sweet_pongal', 'badusha', 'ada_pradhaman'):
        assert d.at[item, 'cuisine_family'] == 'south_indian', item


def test_chennais_payasams_are_south():
    d = _read('chennai').set_index('item')
    for item in ('semiya_pal_payasam', 'millet_payasam', 'semiya_payasam'):
        assert d.at[item, 'cuisine_family'] == 'south_indian', item


def test_western_bakery_is_continental():
    d = _read('bangalore').set_index('item')
    for item in ('vanilla_cake', 'walnut_brownie', 'ice_cream', 'fruit_custard'):
        assert d.at[item, 'cuisine_family'] == 'continental', item


def test_indian_mawa_sweets_that_say_cake_are_not_continental():
    """`milk_cake` and `ajmeri_milk_cake` are mawa sweets, not bakery. The word
    'cake' must not drag them into continental."""
    assert classify('milk_cake') is None
    assert classify('ajmeri_milk_cake') is None
    d = _read('bangalore').set_index('item')
    assert d.at['milk_cake', 'cuisine_family'] != 'continental'


def test_east_and_west_indian_sweets_stay_north_by_design():
    """No East/West bucket exists in the vocabulary, so Bengali (rasgulla,
    rasmalai) and western-Indian (shrikhand, modak) sweets are left grouped with
    the north sweet counter. Asserting it keeps the decision explicit rather than
    accidental."""
    for item in ('rasgulla', 'rasmalai', 'sandesh', 'shrikhand', 'modak',
                 'soan_papdi'):
        assert classify(item) is None, item


def test_classify_matches_whole_tokens_not_substrings():
    """`kesari` is matched as a whole token, so a name that merely contains those
    letters is not swept in."""
    assert classify('kesaria') is None            # substring, not the token
    assert classify('mango_kesari') == 'south_indian'   # 'kesari' is a token
