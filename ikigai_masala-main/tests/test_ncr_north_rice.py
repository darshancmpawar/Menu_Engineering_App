"""NCR's north rice pool (scripts/add_ncr_north_rice.py).

Every NCR counter themes most or all of the week `north`, so `rice` narrows to
NCR's north-Indian rices — and 18 of the original 23 were mixed-veg
pulao/biryani, a family `mixedveg_pulao_biryani_weekly` caps at one day a week.
That left 5 dishes for the other four days: week 1 spent them all and from week
2 the 20-day cooldown had banned every one, so the slot had nothing legal left.

These pin that the imported rices are present, are north, are vegetarian, and —
the part that actually mattered — are OUTSIDE the capped family.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.ontology.paths import city_excel_path
from scripts.add_ncr_north_rice import NEVER, NORTH_RICE, add_rice


def _norm(s):
    return str(s).strip().lower()


@pytest.fixture(scope='module')
def ncr():
    df = pd.read_excel(city_excel_path('NCR'))
    df.columns = [c.strip() for c in df.columns]
    return df


@pytest.fixture(scope='module')
def master():
    df = pd.read_excel(city_excel_path('Bangalore'))
    df.columns = [c.strip() for c in df.columns]
    return df


def _flag(df, col):
    return pd.to_numeric(df.get(col), errors='coerce').fillna(0).astype(int).eq(1)


def test_every_added_rice_is_present_and_filed_as_rice(ncr):
    names = ncr['item'].map(_norm)
    for item in NORTH_RICE:
        rows = ncr[names == item]
        assert len(rows) == 1, f'{item}: expected 1 row, got {len(rows)}'
        assert _norm(rows.iloc[0]['course_type']) == 'rice', (
            f'{item} is filed as {rows.iloc[0]["course_type"]}, not rice')


def test_added_rices_are_north_and_vegetarian(ncr):
    names = ncr['item'].map(_norm)
    added = ncr[names.isin(NORTH_RICE)]
    assert set(added['cuisine_family'].map(_norm)) == {'north_indian'}
    nonveg = {'chicken', 'egg', 'fish', 'mutton', 'prawn', 'seafood'}
    assert not (added['primary_protein'].map(_norm).isin(nonveg)).any()


def test_added_rices_are_outside_the_weekly_capped_family(ncr):
    """The whole point: `mixedveg_pulao_biryani_weekly` allows the family on one
    day a week, so a dish inside it cannot cover the other four."""
    names = ncr['item'].map(_norm)
    added = ncr[names.isin(NORTH_RICE)]
    capped = _flag(added, 'is_mixedveg_pulao') | _flag(added, 'is_mixedveg_biryani')
    assert not capped.any(), (
        f'inside the capped family: {sorted(added.loc[capped, "item"].map(_norm))}')


def test_a_daily_north_rice_slot_has_enough_uncapped_dishes(ncr):
    """~one distinct dish per working day in the 20-day cooldown window plus the
    week being planned = floor(20*5/7) + 5 = 19."""
    ct = ncr['course_type'].map(_norm)
    cf = ncr['cuisine_family'].map(_norm)
    north = ncr[ct.eq('rice') & cf.eq('north_indian')]
    capped = _flag(north, 'is_mixedveg_pulao') | _flag(north, 'is_mixedveg_biryani')
    assert len(north[~capped]) >= 19


def test_white_rice_variants_were_not_imported(ncr):
    """They belong to the `white_rice` CONST slot, not the flavoured rice pool."""
    ct = ncr['course_type'].map(_norm)
    rice_names = set(ncr[ct.eq('rice')]['item'].map(_norm))
    for item in NEVER:
        assert item not in (rice_names & set(NORTH_RICE))


def test_ids_and_names_unique(ncr):
    assert ncr['item'].duplicated().sum() == 0
    assert ncr['item_id'].duplicated().sum() == 0


def test_schema_unchanged(ncr, master):
    assert list(ncr.columns) == list(master.columns)


def test_rerun_is_a_noop(ncr, master):
    out = add_rice(master, ncr.copy())
    assert len(out) == len(ncr), 're-running added rows again'
