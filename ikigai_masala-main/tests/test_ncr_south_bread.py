"""NCR's South Indian bread pool (scripts/ncr_south_bread.py).

NCR carried three south breads — `idli`, `idly`, `malabar_paratha` — and the
first two are one dish spelled twice AND both `is_rice_bread`. On a counter
that themes a weekday `south` (Junglee Games, Thursday) the bread cuisine lock
narrowed the slot to those three, so once `malabar_paratha` went on cooldown
the slot was *forced* onto a rice-bread. Coupling rule 38 then demanded a
liquid rice, and the same cuisine lock offers a south day 16 rices of which
none is liquid (every khichdi is north Indian) — INFEASIBLE, with no starved
slot to point at.

These pin the shape that makes the south day servable: enough south breads to
outlast the cooldown, and enough of them NOT rice-bread that the coupling chain
stays a choice.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.ontology.paths import city_excel_path
from scripts.ncr_south_bread import (
    DROP_DUPLICATES,
    IMPORT,
    RETAG,
    SOUTH,
    SOUTH_BREAD_NON_RICE,
    drop_duplicates,
    import_breads,
    retag,
)


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


def _south_breads(df):
    ct = df['course_type'].map(_norm)
    cf = df['cuisine_family'].map(_norm)
    return df[ct.eq('bread') & cf.eq(SOUTH)]


def _flag(df, col):
    return pd.to_numeric(df.get(col), errors='coerce').fillna(0).astype(int).eq(1)


def test_every_imported_bread_is_present_and_south(ncr):
    names = ncr['item'].map(_norm)
    for item in IMPORT:
        rows = ncr[names == item]
        assert len(rows) == 1, f'{item}: expected 1 row, got {len(rows)}'
        r = rows.iloc[0]
        assert _norm(r['course_type']) == 'bread', f'{item} is not a bread'
        assert _norm(r['cuisine_family']) == SOUTH, f'{item} is not {SOUTH}'


def test_south_day_has_a_non_rice_bread_to_fall_back_on(ncr):
    """The constraint that actually mattered.

    A south day whose only breads are rice-breads *forces* the coupling chain
    (rice-bread => liquid rice), and NCR has no south liquid rice. The pool
    needs enough non-rice-bread south dishes that one survives the 20-day
    cooldown: a south day comes round once a week, so ~4 weeks of window plus
    the week being planned.
    """
    b = _south_breads(ncr)
    non_rice = b[~_flag(b, 'is_rice_bread')]
    assert len(non_rice) >= 5, (
        f'only {len(non_rice)} non-rice-bread south bread(s): '
        f'{sorted(non_rice["item"].map(_norm))}'
    )
    for item in SOUTH_BREAD_NON_RICE:
        assert item in set(non_rice['item'].map(_norm)), (
            f'{item} was imported to be a non-rice-bread option but is flagged '
            f'is_rice_bread'
        )


def test_south_bread_pool_outlasts_the_cooldown(ncr):
    """One south day a week over a 20-day cooldown window needs ~5 distinct."""
    assert len(_south_breads(ncr)) >= 12


def test_idli_family_is_south_and_flagged_rice_bread(ncr):
    names = ncr['item'].map(_norm)
    for item in RETAG:
        rows = ncr[names == item]
        assert len(rows) == 1, f'{item}: expected 1 row, got {len(rows)}'
        r = rows.iloc[0]
        assert _norm(r['cuisine_family']) == SOUTH, f'{item} is not {SOUTH}'
        assert int(pd.to_numeric(r.get('is_rice_bread'), errors='coerce') or 0) == 1
    assert _norm(ncr[names == 'mini_idli'].iloc[0]['sub_category']) != 'tandoor'


def test_duplicate_spellings_are_gone(ncr):
    names = set(ncr['item'].map(_norm))
    for dup, keep in DROP_DUPLICATES.items():
        assert dup not in names, f'{dup} is a duplicate of {keep}'
        assert keep in names, f'{keep} (the kept spelling) is missing'


def test_ids_and_names_unique(ncr):
    assert ncr['item'].duplicated().sum() == 0
    assert ncr['item_id'].duplicated().sum() == 0


def test_schema_unchanged(ncr, master):
    assert list(ncr.columns) == list(master.columns)


def test_rerun_is_a_noop(ncr, master):
    out = ncr.copy()
    retag(out)
    out = drop_duplicates(out)
    out = import_breads(master, out)
    assert len(out) == len(ncr), 're-running changed the row count'
    assert (sorted(out['item'].map(_norm))
            == sorted(ncr['item'].map(_norm))), 're-running changed the dishes'


# --------------------------------------------------------------------------
# The cadence: a south bread is a treat on a North Indian site, not the roti
# --------------------------------------------------------------------------
# Giving NCR a real south bread pool means a south-themed weekday would now
# serve a dosa/idli EVERY week, because the cuisine lock narrows the slot to
# them. `ncr_south_bread_cadence` holds the whole family off for 15 days after
# any one is served, so with a weekly south day it lands about once every three
# weeks.

CADENCE = 'ncr_south_bread_cadence'


@pytest.fixture(scope='module')
def ncr_rules():
    from src.menu_rules.menu_rule_loader import MenuRuleLoader
    return MenuRuleLoader().load_for_city('NCR')


@pytest.fixture(scope='module')
def cadence(ncr_rules):
    rules = [r for r in ncr_rules if r.name == CADENCE]
    assert rules, f'{CADENCE} is not in the NCR ruleset'
    return rules[0]


def test_cadence_rule_is_valid_and_spans_more_than_a_week(cadence):
    assert cadence.validate_config(), cadence.validation_errors()
    assert cadence.window_days > 7, (
        'a window inside one week is enforceable within a plan and does not '
        'need a history read'
    )


def test_cadence_covers_every_south_bread_and_only_breads(cadence, ncr):
    matched = cadence.matching_items(ncr)
    south = set(_south_breads(ncr)['item'].map(_norm))
    assert matched == south, (
        f'missing {sorted(south - matched)}, unexpected {sorted(matched - south)}')


def test_banning_the_family_leaves_the_south_day_a_bread(ncr_rules, ncr):
    """The safety property.

    When the cadence has banned every south bread, the cuisine lock finds no
    south candidate and falls back to the whole bread pool — so the south day
    serves a chapati instead of the plan going INFEASIBLE. Without that
    fallback this rule would be a weekly guarantee of failure.
    """
    import datetime as dt

    from src.ontology.repository import repository

    df, pools = repository.filtered_menu_data('NCR', None)
    by_name = {r.name: r for r in ncr_rules}
    cad = by_name[CADENCE]
    day = dt.date(2026, 9, 3)
    ctx = {'cfg': None, 'pools': pools, 'ricebread_ban_day': {},
           'extra_repeatable': {},
           'banned_by_date': {day: set(cad.matching_items(df))}}
    pool = by_name['item_cooldown_20d'].pre_filter_pool(
        pools['bread'].copy(), day, 'bread', 'south', ctx)
    pool = by_name['theme_cuisine_filter'].pre_filter_pool(
        pool, day, 'bread', 'south', ctx)
    assert len(pool) > 0, 'the south day has no bread left at all'
    left = set(pool['item'].map(_norm))
    assert not (left & set(cad.matching_items(df))), (
        'a banned south bread survived the cadence')


def test_ncr_plans_from_the_full_city_list(ncr):
    """Every NCR client draws on the whole NCR list, not one site's pool.

    NCR has no `common` pool — all 1,630 rows are tagged to one of eight sites
    — so per-client narrowing would hand a client a fraction of the list.
    """
    from src.constants import FULL_POOL_CITIES
    from src.ontology.repository import repository

    assert 'ncr' in FULL_POOL_CITIES
    full, _ = repository.filtered_menu_data('NCR', None)
    narrowed, _ = repository.filtered_menu_data('NCR', ['stryker'])
    assert len(narrowed) == len(full), (
        'a client naming one site pool got fewer items than the full list')
