"""The item lists carry no rows named for a category instead of a dish.

Eleven rows — `sweet`, `veg_gravy`, `salad`, `chutney`, … — named a *category*, not
a dish. A menu that prints "Sweet" tells the diner nothing, and no colour /
ingredient / variety rule can reason about a row it cannot identify. The client
chose removal over renaming (D3 in docs/data_fixes_for_client.md); this pins that
they stay gone, because a re-import through the normaliser would bring them back.
"""

from __future__ import annotations

import os

import pandas as pd
import pytest

from scripts.remove_generic_rows import CITY_ITEMS, GENERIC_ROWS, apply_removals


def _read(city):
    return pd.read_excel(os.path.join(CITY_ITEMS, f'{city}.xlsx'))


@pytest.mark.parametrize('city', sorted(GENERIC_ROWS))
def test_no_generic_row_survives(city):
    present = set(_read(city)['item'].astype(str).str.strip())
    leftover = sorted(set(GENERIC_ROWS[city]) & present)
    assert not leftover, f'{city}: generic rows still present: {leftover}'


@pytest.mark.parametrize('city', sorted(GENERIC_ROWS))
def test_rerunning_the_removal_changes_nothing(city):
    _after, removed = apply_removals(_read(city), city)
    assert not removed, removed


def test_removal_matches_whole_names_not_substrings():
    """`sweet` must not drag `dry_sweet` with it. Since the real workbook already
    has both removed, prove the matcher is exact on a synthetic frame."""
    df = pd.DataFrame({'item': ['sweet', 'dry_sweet', 'sweet_lassi']})
    after, removed = apply_removals(df, 'pune')
    assert removed == ['sweet']
    assert set(after['item']) == {'dry_sweet', 'sweet_lassi'}


#: course_types the removed rows came from — these must stay comfortably filled.
#: (Not every required slot: Chennai's curd / rasam / curd_rice are legitimately
#: tiny, which is D4, and no generic row was removed from them.)
_AFFECTED = {
    'Chennai': ['veg_dry', 'soup', 'dessert', 'veg_gravy', 'salad'],
    'Pune': ['salad', 'dessert'],
    # NCR's bare labels sat mostly in veg_gravy (the misfiled dessert/gravy/
    # veg_dry names) plus one each in dal/rice/salad/curd_side. rasam/sambar are
    # NOT here: their only row WAS the bare label, so removing it takes NCR to no
    # rasam/sambar station at all (declared-out in ontology_categories), which is
    # correct for a North Indian list — not a starved required slot.
    'NCR': ['veg_gravy', 'dal', 'rice', 'salad', 'curd_side'],
}


def test_removal_does_not_starve_an_affected_slot():
    """The only real risk: emptying a slot the ontology must cover, which would
    make PoolBuilder.build_pools raise. build_pools succeeding already proves no
    *required* slot is empty; this additionally pins that the slots the removals
    touched can still fill a unique 7-day week (the smallest, Chennai soup, is 8
    after darbar_soup left)."""
    from api.config import city_excel_path, city_required_slots
    from src.preprocessor.data_cleanser import DataCleanser
    from src.preprocessor.excel_reader import ExcelReader
    from src.preprocessor.pool_builder import PoolBuilder
    for city, slots in _AFFECTED.items():
        df = DataCleanser(ExcelReader(city_excel_path(city)).read()).clean()
        pools = PoolBuilder().build_pools(
            df, required_slots=city_required_slots(city))
        for slot in slots:
            assert len(pools[slot]) >= 7, (city, slot, len(pools[slot]))
