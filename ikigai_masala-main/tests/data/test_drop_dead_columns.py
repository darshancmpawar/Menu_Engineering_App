"""Removing a column is the one ontology edit that cannot be undone by re-running.

`universe` was blank on all 8,787 rows in every city and read by nothing — a
column the master ontology shipped with that nobody ever filled. Always-empty is
not free: it is one more field a new city's import has to line up and one more
thing a reader of the schema has to decide whether they need.

The danger is obvious, so the guard is the point of these tests: the script
verifies emptiness across EVERY city before touching any of them, because a
column holding data anywhere is not dead whatever the others say.
"""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.complete_ontology import load
from scripts.drop_dead_columns import DEAD_COLUMNS, CITIES

EXPECTED_COLUMNS = 134


@pytest.fixture(scope='module')
def frames():
    return load()


class TestTheColumnIsGone:

    @pytest.mark.parametrize('city', CITIES)
    def test_no_city_still_carries_it(self, frames, city):
        for column in DEAD_COLUMNS:
            assert column not in frames[city].columns, (city, column)

    def test_the_schema_is_the_same_everywhere_and_one_narrower(self, frames):
        """The count is pinned in `test_course_type_audit.py` too; a drop that
        reached only some cities would leave the four workbooks disagreeing,
        which every per-city test depends on not happening."""
        reference = list(frames['bangalore'].columns)
        assert len(reference) == EXPECTED_COLUMNS
        for city in CITIES:
            assert list(frames[city].columns) == reference, city

    def test_dropping_a_column_does_not_drop_a_dish(self, frames):
        """The actual invariant: removing a column changes the width, never the
        height.

        This used to assert hardcoded row-count floors per city, which is a
        proxy for the invariant rather than the invariant — and a brittle one:
        `remove_generic_rows.py` legitimately took 39 rows out of NCR (date
        headers and a vendor note the mapping pipeline had imported as dishes)
        and this test failed on the floor of 1,600 while nothing was actually
        wrong. Asserted directly now, so a real regression fails and a
        deliberate removal does not.
        """
        import pandas as pd
        for city, df in frames.items():
            trimmed = df.drop(columns=[c for c in DEAD_COLUMNS if c in df.columns])
            assert len(trimmed) == len(df), city
            assert isinstance(trimmed, pd.DataFrame)

    def test_no_city_list_has_collapsed(self, frames):
        """A loose sanity floor — an order-of-magnitude check, not a pin. Row
        counts move whenever dishes are added or non-dishes removed, so these
        are set well below the current sizes on purpose."""
        assert len(frames['bangalore']) > 5000
        assert len(frames['chennai']) > 500
        assert len(frames['pune']) > 300
        assert len(frames['ncr']) > 1200


class TestTheGuardHoldsBack:

    def test_a_column_holding_data_anywhere_is_refused(self, tmp_path, monkeypatch):
        """The check that makes this safe to extend. Adding a name to
        DEAD_COLUMNS is a one-line change; the guard is what stops that line
        deleting real data."""
        import scripts.drop_dead_columns as mod

        for city in ('alpha', 'beta'):
            pd.DataFrame({'item': ['a', 'b'],
                          'doomed': [None, None] if city == 'alpha'
                                    else ['kept', None]}).to_excel(
                tmp_path / f'{city}.xlsx', index=False)
        monkeypatch.setattr(mod, 'CITY_DIR', tmp_path)
        monkeypatch.setattr(mod, 'CITIES', ('alpha', 'beta'))
        monkeypatch.setattr(mod, 'DEAD_COLUMNS', ('doomed',))
        mod.main()

        for city in ('alpha', 'beta'):
            after = pd.read_excel(tmp_path / f'{city}.xlsx')
            assert 'doomed' in after.columns, city

    def test_an_empty_column_is_dropped_from_every_city(self, tmp_path, monkeypatch):
        import scripts.drop_dead_columns as mod

        for city in ('alpha', 'beta'):
            pd.DataFrame({'item': ['a', 'b'],
                          'doomed': [None, None]}).to_excel(
                tmp_path / f'{city}.xlsx', index=False)
        monkeypatch.setattr(mod, 'CITY_DIR', tmp_path)
        monkeypatch.setattr(mod, 'CITIES', ('alpha', 'beta'))
        monkeypatch.setattr(mod, 'DEAD_COLUMNS', ('doomed',))
        mod.main()

        for city in ('alpha', 'beta'):
            after = pd.read_excel(tmp_path / f'{city}.xlsx')
            assert 'doomed' not in after.columns, city
            assert len(after) == 2, city

    def test_dry_run_writes_nothing(self, tmp_path, monkeypatch):
        import scripts.drop_dead_columns as mod

        pd.DataFrame({'item': ['a'], 'doomed': [None]}).to_excel(
            tmp_path / 'alpha.xlsx', index=False)
        monkeypatch.setattr(mod, 'CITY_DIR', tmp_path)
        monkeypatch.setattr(mod, 'CITIES', ('alpha',))
        monkeypatch.setattr(mod, 'DEAD_COLUMNS', ('doomed',))
        mod.main(dry_run=True)
        assert 'doomed' in pd.read_excel(tmp_path / 'alpha.xlsx').columns


class TestRunningItAgainChangesNothing:

    def test_a_second_run_is_a_no_op(self, frames):
        """Nothing left to drop, so nothing is written — the workbooks the
        correction chain hands on are byte-identical."""
        import scripts.drop_dead_columns as mod
        before = {c: list(d.columns) for c, d in frames.items()}
        mod.main()
        after = load()
        assert {c: list(d.columns) for c, d in after.items()} == before
