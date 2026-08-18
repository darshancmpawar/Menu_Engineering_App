"""The NCR fuzzy-merge reversal stays applied and stays surgical.

The NCR workbook fuzzy-matched dish names to the master at 0.82 similarity and
overwrote the source name with the match. Most were spelling variants and are
correct to keep; 13 collapsed genuinely different dishes (aloo_matar[peas] ->
aloo_tamatar[tomato], punjabi_kadhi[yogurt curry] -> punjabi_kadai[wok], …).
`scripts/ncr_fuzzy_unmerge.py` reverts exactly those. This pins that it stays
reverted after a re-import (which would bring the merged names back) and — the
other half — that a legitimate spelling merge is left untouched, so the reversal
did not overcorrect.
"""

from __future__ import annotations

import os

import pandas as pd

from scripts.ncr_fuzzy_unmerge import (
    CITY_ITEMS, RENAMES, SPLITS, apply_unmerge)


def _read():
    return pd.read_excel(os.path.join(CITY_ITEMS, 'ncr.xlsx'))


def _names():
    return set(_read()['item'].astype(str).str.strip())


def test_no_wrong_merge_name_survives():
    names = _names()
    still = sorted(m for m in RENAMES if m in names)
    assert not still, f'merged names still present: {still}'


def test_every_restored_dish_is_present():
    names = _names()
    missing = sorted(r for r in RENAMES.values() if r not in names)
    missing += [new for _keep, new in SPLITS if new not in names]
    assert not missing, f'restored dishes missing: {missing}'


def test_collisions_kept_both_dishes():
    """A real dish and a spelling variant both merged into these; the split must
    leave BOTH the kept master and the restored source present and distinct."""
    names = _names()
    for keep, new in SPLITS:
        assert keep in names, keep
        assert new in names, new


def test_attribute_fixes_applied():
    df = _read()
    bhuna = df[df['item'] == 'bhuna_chicken'].iloc[0]
    assert bhuna['sub_category'] == 'chicken_bhuna_kadai'  # not chinese
    assert int(bhuna['is_chinese_chicken_gravy']) == 0
    achari = df[df['item'] == 'paneer_achari_masala'].iloc[0]
    assert str(achari['primary_protein']) == 'paneer'
    assert int(achari['is_paneer_gravy']) == 1


def test_reversal_did_not_touch_a_pure_spelling_merge():
    """The point of the surgical list: a real spelling variant stays merged.
    `ajwain_paratha -> ajawin_paratha` is such a case — the master spelling wins,
    and we must NOT have resurrected the source spelling."""
    names = _names()
    assert 'ajawin_paratha' in names
    assert 'ajwain_paratha' not in names
    # kadai (wok) dishes stay kadai; only the kadhi (yogurt curry) ones reverted
    assert 'kadai_paneer' in names
    assert 'paneer_kadai' in names           # the real kadai paneer, kept


def test_rerun_is_a_noop():
    _after, changes = apply_unmerge(_read())
    real = [c for c in changes if c[1] != 'SKIP']
    assert not real, real


def test_no_duplicate_ids_or_names():
    df = _read()
    assert df['item_id'].duplicated().sum() == 0
    assert df['item'].duplicated().sum() == 0
