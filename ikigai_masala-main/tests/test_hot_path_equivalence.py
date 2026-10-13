"""The two fast paths answer exactly what the slow ones answered.

Both are pure speed changes on a path the solver walks hundreds of thousands
of times in one `/plan`, and both would fail SILENTLY if the equivalence ever
stopped holding: a value materialised differently, a blank read as a value.
Nothing raises, nothing logs, a plausible menu comes out — the shape of
failure this repo keeps guarding against.

So the guard is the equivalence itself, measured against the five real
workbooks rather than a fixture, because the assumption is about the DATA and
not about the code:

1. `menu_solver._build_decision_variables` builds a cell's candidate rows with
   `to_numpy(dtype=object)` instead of `.iloc[j]`. The values must be the ones
   `to_dict('records')` gives — the reference the rule layer was written
   against — and that is a claim about the dtypes these five workbooks carry,
   which a re-cut workbook or a pandas upgrade could change under it.
2. `_norm_str` short-circuits a `str` past `pd.isna`.

No solver, no database, no CP-SAT. See note 42.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.ontology.repository import repository
from src.preprocessor.column_mapper import _norm_str

CITIES = ['Bangalore', 'Hyderabad', 'Chennai', 'Pune', 'NCR']

#: Enough rows per pool to carry every dtype the workbook uses, without
#: re-materialising five full city lists for a check meant to be cheap.
SAMPLE = 25


def _records_via_numpy(frame: pd.DataFrame):
    """What `_build_decision_variables` does, in one place both can read."""
    cols = list(frame.columns)
    return [dict(zip(cols, vals)) for vals in frame.to_numpy(dtype=object)]


@pytest.mark.parametrize('city', CITIES)
def test_numpy_rows_equal_to_dict_rows(city):
    _df, pools = repository.menu_data(city)
    for slot, pool in sorted(pools.items()):
        if not len(pool):
            continue
        head = pool.head(SAMPLE)
        fast, slow = _records_via_numpy(head), head.to_dict('records')
        assert len(fast) == len(slow)
        for i, (a, b) in enumerate(zip(fast, slow)):
            assert a.keys() == b.keys(), f'{city}/{slot} row {i}: columns differ'
            for col in b:
                # `repr` rather than `==`: NaN is not equal to itself, and a
                # NaN silently becoming the string 'nan' is exactly the
                # substitution `_norm_cell` exists to undo.
                assert repr(a[col]) == repr(b[col]), (
                    f'{city}/{slot} row {i} column {col!r}: '
                    f'{a[col]!r} via numpy, {b[col]!r} via to_dict')


@pytest.mark.parametrize('value', [
    '', ' ', 'Aloo Gobi', ' PANEER ', 'nan', '\tdal\n', '0', 'None'])
def test_norm_str_fast_path_matches_the_general_one(value):
    assert _norm_str(value) == (
        '' if pd.isna(value) else str(value).strip().lower())


@pytest.mark.parametrize('value', [None, float('nan'), pd.NaT, 1, 1.5, True])
def test_norm_str_still_handles_what_is_not_a_string(value):
    assert _norm_str(value) == ('' if pd.isna(value)
                                else str(value).strip().lower())


if __name__ == '__main__':      # a runnable check without pytest
    raise SystemExit(pytest.main([__file__, '-q']))
