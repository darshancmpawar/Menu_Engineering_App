"""NCR savoury dishes mislabeled `cuisine_family = continental` stay corrected.

The mapping pipeline tagged 17 North Indian chicken curries and 7 Indian
starters `continental`. ThemeSlotFilterRule then hid them on every non-continental
day, and no NCR client runs a continental day — so they were unservable. The fix
(`scripts/ncr_cuisine_corrections.py`) retags exactly those two cuisine-main slots
to `north_indian`, and leaves the genuinely-continental veg_dry / soup rows alone.
"""

from __future__ import annotations

import os

import pandas as pd

from scripts.ncr_cuisine_corrections import (
    CITY_ITEMS, FIX_SLOTS, apply_corrections)


def _read():
    return pd.read_excel(os.path.join(CITY_ITEMS, 'ncr.xlsx'))


def test_no_continental_left_in_the_fixed_slots():
    df = _read()
    course = df['course_type'].astype(str).str.strip()
    cuisine = df['cuisine_family'].astype(str).str.strip().str.lower()
    offenders = df.loc[course.isin(FIX_SLOTS) & (cuisine == 'continental'), 'item']
    assert list(offenders) == [], list(offenders)


def test_the_north_indian_chicken_is_north_not_continental():
    df = _read()
    for name in ['butter_chicken', 'chicken_rogan_josh', 'chicken_lababdar']:
        row = df[df['item'] == name].iloc[0]
        assert str(row['cuisine_family']).lower() == 'north_indian', name


def test_indian_starters_are_north():
    df = _read()
    for name in ['samosa_chaat', 'kachori', 'aloo_bajji']:
        row = df[df['item'] == name].iloc[0]
        assert str(row['cuisine_family']).lower() == 'north_indian', name


def test_genuinely_continental_rows_are_untouched():
    """The fix is scoped to two slots; western veg_dry / soup rows keep their
    correct continental tag."""
    df = _read()
    for name in ['caramelized_onion', 'stirfried_vegetable', 'sweet_corn_soup']:
        row = df[df['item'] == name].iloc[0]
        assert str(row['cuisine_family']).lower() == 'continental', name


def test_rerun_is_a_noop():
    _after, changed = apply_corrections(_read())
    assert changed == [], changed
