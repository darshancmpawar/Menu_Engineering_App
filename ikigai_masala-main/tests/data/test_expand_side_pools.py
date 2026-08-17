"""The side-slot pool expansion (scripts/expand_side_pools.py).

Adds 7 dishes to each of healthy_rice / dessert / flavoured-chapati (bread) /
starter in every city, so those small pools don't drain empty under the cooldown.
Pins: the dishes are present and correctly filed, veg-only, tagged with the
city's pool convention (common vs blank), the curated clones carry clean flags,
the schema is unchanged, ids/names stay unique, and re-running adds nothing.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.ontology.paths import city_excel_path
from scripts.expand_side_pools import (
    CATEGORIES, NEW_DISHES, expand, _norm, _is_veg,
)

CITY_KEY = {'bangalore': 'Bangalore', 'pune': 'Pune',
            'chennai': 'Chennai', 'ncr': 'NCR'}


@pytest.fixture(scope='module')
def dfs():
    out = {}
    for slug, name in CITY_KEY.items():
        df = pd.read_excel(city_excel_path(name))
        df.columns = [c.strip() for c in df.columns]
        out[slug] = df
    return out


def _cat(df, cat):
    return df[df['course_type'].map(_norm) == cat]


def test_each_category_grew_by_at_least_seven(dfs):
    """Every city gained the 7 curated dishes in each of the four categories.

    ``>=`` not ``==``: a (city, category) in CITY_SHARE_TARGETS is topped up
    further by the sharing pass (Pune bread also goes to 22), so the curated
    seven are a floor, not the whole story.
    """
    baseline = {
        'bangalore': {'healthy_rice': 91, 'dessert': 249, 'starter': 148, 'bread': 253},
        'pune':      {'healthy_rice': 1,  'dessert': 44,  'starter': 0,   'bread': 2},
        'chennai':   {'healthy_rice': 2,  'dessert': 29,  'starter': 27,  'bread': 29},
        'ncr':       {'healthy_rice': 2,  'dessert': 176, 'starter': 8,   'bread': 59},
    }
    # `scripts/ncr_bread_misfiles.py` then took 12 rows back OUT of NCR's bread
    # pool — curries and a dal the mapping pipeline had filed as bread
    # (paneer_jaipuri and friends). That correction is deliberate and must not be
    # read as the expansion under-delivering, so the expected floor accounts for
    # it rather than the test being loosened.
    removed_after = {('ncr', 'bread'): 12}
    for slug, df in dfs.items():
        for cat in CATEGORIES:
            got = len(_cat(df, cat))
            want = baseline[slug][cat] + 7 - removed_after.get((slug, cat), 0)
            assert got >= want, f'{slug}/{cat}: expected >= {want}, got {got}'


def test_strict_slot_targets_are_met(dfs):
    """Every (city, category) a client serves under the STRICT no-repeat rule
    carries enough distinct dishes for a cooldown window (~19); the targets are
    set to 22 for margin. rasam/sambar are not cooldown-exempt, so this is the
    only thing standing between them and an empty pool in week 3."""
    from scripts.expand_side_pools import CITY_SHARE_TARGETS
    for (slug, cat), target in CITY_SHARE_TARGETS.items():
        got = len(_cat(dfs[slug], cat))
        assert got >= target, f'{slug}/{cat}: {got} dishes, target {target}'


def test_curated_flavoured_chapatis_present_everywhere(dfs):
    for slug, df in dfs.items():
        breads = set(_cat(df, 'bread')['item'].map(_norm))
        for name, *_ in NEW_DISHES['bread'][:7]:
            assert _norm(name) in breads, f'{slug} missing bread {name}'


def test_all_additions_are_veg(dfs):
    """No non-veg leaked into any of the four categories (matters for Pune)."""
    for slug, df in dfs.items():
        for cat in CATEGORIES:
            sub = _cat(df, cat)
            nonveg = sub[~sub.apply(_is_veg, axis=1)]
            assert len(nonveg) == 0, (
                f'{slug}/{cat} has non-veg: {list(nonveg["item"])[:5]}')


def test_pool_token_matches_city_convention(dfs):
    # common-cities: every row (incl. additions) is common. NCR: no common.
    for slug in ('pune', 'chennai'):
        cl = dfs[slug]['client'].map(_norm)
        assert (cl == 'common').all(), f'{slug} has a non-common row'
    ncr_cl = dfs['ncr']['client'].map(_norm)
    assert not ncr_cl.str.contains('common').any()


def test_curated_dessert_has_clean_flags(dfs):
    """A cloned dessert must not inherit the gulab_jamun template's specifics."""
    df = dfs['bangalore']
    r = df[df['item'].map(_norm) == 'apple_halwa']
    assert len(r) == 1
    r = r.iloc[0]
    assert int(r.get('is_dessert', 0)) == 1
    assert int(r.get('is_sweet', 0)) == 1
    assert int(r.get('is_fried', 0)) == 0            # halwa is not fried
    assert int(r.get('is_sugar_syrup_heavy_dessert', 0)) == 0


def test_schema_and_uniqueness(dfs):
    blr_cols = list(dfs['bangalore'].columns)
    for slug, df in dfs.items():
        assert list(df.columns) == blr_cols, f'{slug} column drift'
        assert df['item_id'].duplicated().sum() == 0, f'{slug} dup ids'
        assert df['item'].duplicated().sum() == 0, f'{slug} dup names'


def test_rerun_is_a_noop():
    """Re-running the expansion on the committed files adds nothing."""
    summary = expand(dry_run=True)
    added = {k: v for k, v in summary.items() if v}
    assert not added, f'expansion is not idempotent: {added}'
