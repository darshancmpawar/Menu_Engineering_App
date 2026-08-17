"""Curries filed as bread in NCR (scripts/ncr_bread_misfiles.py).

`paneer_jaipuri` — a paneer curry, primary_protein=paneer — sat in NCR's bread
pool with sub_category=flavoured_paratha, so a counter could serve it as the
day's roti. Eleven siblings had the same fingerprint (blank cuisine_family,
key_ingredient copied from the first word of the name). This pins that they are
out of the bread slot and filed where they belong.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.ontology.paths import city_excel_path
from scripts.ncr_bread_misfiles import REFILE, REMOVE, fix


@pytest.fixture(scope='module')
def ncr():
    df = pd.read_excel(city_excel_path('NCR'))
    df.columns = [c.strip() for c in df.columns]
    return df


def _norm(s):
    return str(s).strip().lower()


def test_no_curry_is_filed_as_bread(ncr):
    bread = set(ncr[ncr['course_type'].map(_norm) == 'bread']['item'].map(_norm))
    for item in REFILE:
        assert item not in bread, f'{item} is still in the bread pool'


def test_each_refiled_dish_landed_in_its_category(ncr):
    names = ncr['item'].map(_norm)
    for item, target in REFILE.items():
        rows = ncr[names == item]
        assert len(rows) == 1, f'{item}: expected 1 row, got {len(rows)}'
        assert _norm(rows.iloc[0]['course_type']) == target, (
            f'{item} should be {target}, is {rows.iloc[0]["course_type"]}')


def test_paneer_jaipuri_is_a_paneer_gravy(ncr):
    """The dish that started this: it must be a gravy, keyed on paneer, and
    carry no bread flags."""
    r = ncr[ncr['item'].map(_norm) == 'paneer_jaipuri']
    assert len(r) == 1
    r = r.iloc[0]
    assert _norm(r['course_type']) == 'veg_gravy'
    assert _norm(r.get('key_ingredient')) == 'paneer'
    for flag in ('is_bread', 'is_maida_bread', 'is_plain_phulka_chapathi'):
        if flag in ncr.columns:
            assert int(pd.to_numeric(r.get(flag), errors='coerce') or 0) == 0, flag


def test_removed_rows_are_gone(ncr):
    names = set(ncr['item'].map(_norm))
    for item in REMOVE:
        assert item not in names, f'{item} should have been removed'


def test_ids_and_names_unique(ncr):
    assert ncr['item'].duplicated().sum() == 0
    assert ncr['item_id'].duplicated().sum() == 0


def test_rerun_is_a_noop(ncr):
    out = fix(ncr.copy())
    assert len(out) == len(ncr), 're-running removed more rows'
    before = ncr['course_type'].map(_norm).value_counts().to_dict()
    after = out['course_type'].map(_norm).value_counts().to_dict()
    assert before == after, 're-running changed course_type counts'
