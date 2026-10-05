"""Per-service counters: lunch and dinner can be configured apart.

A counter carries `meals` saying which services it runs at. ABSENT means every
service, which is what every counter stored before this meant — so the whole
feature is invisible until somebody splits a service out, and no row is
migrated.

Two things have to hold or this is worse than not having it:

  * the tag must SURVIVE. `normalize_counter` returns a fixed dict and drops
    any key not in it, so a tag that is written and then silently dropped on
    the next read looks exactly like a saved setting that does nothing;
  * a service with no counter of its own must still plan. The filter runs in
    `_counters_list`, which every caller goes through, so an over-strict
    filter would hand the solver an empty list and fail a menu.
"""

from __future__ import annotations

from src.client.client_config import (
    counter_serves,
    default_counter,
    normalize_counter,
)
from src.history import DINNER, LUNCH


def _counter(name, meals=None):
    raw = dict(default_counter(0, name), name=name)
    if meals is not None:
        raw['meals'] = meals
    return raw


class TestTheTagSurvives:
    def test_a_tag_is_kept_through_normalisation(self):
        assert normalize_counter(_counter('Veg', [LUNCH]))['meals'] == [LUNCH]

    def test_an_untagged_counter_gains_no_key(self):
        """Not defaulted to every meal: the editor dirty-checks counters by
        equality, and a key appearing on load would read as an edit nobody
        made, on every client that never used this."""
        assert 'meals' not in normalize_counter(_counter('Veg'))

    def test_the_tag_is_ordered_and_cleaned(self):
        got = normalize_counter(_counter('Veg', ['DINNER', 'lunch', 'brunch']))
        assert got['meals'] == [LUNCH, DINNER]

    def test_an_all_junk_tag_falls_back_to_every_service(self):
        assert 'meals' not in normalize_counter(_counter('Veg', ['brunch']))


class TestWhoServesWhat:
    def test_an_untagged_counter_serves_every_service(self):
        c = normalize_counter(_counter('Veg'))
        assert counter_serves(c, LUNCH) and counter_serves(c, DINNER)

    def test_a_tagged_counter_serves_only_its_own(self):
        c = normalize_counter(_counter('Veg', [DINNER]))
        assert counter_serves(c, DINNER) and not counter_serves(c, LUNCH)

    def test_no_meal_asked_means_every_counter(self):
        """`counter_serves(c, None)` is the un-scoped read every caller that
        does not care about services still makes."""
        assert counter_serves(normalize_counter(_counter('Veg', [DINNER])), None)


class TestTheFilterInTheLoader:
    """`_counters_list` is the only place the filter lives, so `counter_index`
    keeps meaning "index into the list you were handed"."""

    def _loader(self, counters):
        from src.client.client_config import ClientConfigLoader
        loader = ClientConfigLoader.__new__(ClientConfigLoader)
        loader._read_counters_column = lambda _name: counters        # noqa: SLF001
        return loader

    def test_a_split_client_sees_only_its_service(self):
        loader = self._loader([_counter('Veg lunch', [LUNCH]),
                               _counter('Veg dinner', [DINNER])])
        assert [c['name'] for c in loader._counters_list('X', LUNCH)] == ['Veg lunch']
        assert [c['name'] for c in loader._counters_list('X', DINNER)] == ['Veg dinner']

    def test_an_unsplit_client_is_unchanged(self):
        """The whole point: nothing moves until somebody splits a service."""
        loader = self._loader([_counter('Main'), _counter('Chinese')])
        for meal in (None, LUNCH, DINNER):
            assert [c['name'] for c in loader._counters_list('X', meal)] == \
                ['Main', 'Chinese']

    def test_a_shared_counter_shows_up_in_both(self):
        loader = self._loader([_counter('Shared', [LUNCH, DINNER]),
                               _counter('Dinner only', [DINNER])])
        assert len(loader._counters_list('X', LUNCH)) == 1
        assert len(loader._counters_list('X', DINNER)) == 2

    def test_asking_for_nothing_in_particular_returns_all(self):
        loader = self._loader([_counter('A', [LUNCH]), _counter('B', [DINNER])])
        assert len(loader._counters_list('X', None)) == 2

    def test_a_service_with_no_counter_degrades_instead_of_emptying(self, caplog):
        """An empty counter list is an opaque solver failure. Fall back to all
        of them — and say so, because a service quietly planned from another
        service's stations is worse than a loud one."""
        loader = self._loader([_counter('Lunch only', [LUNCH])])
        with caplog.at_level('WARNING'):
            got = loader._counters_list('X', DINNER)
        assert [c['name'] for c in got] == ['Lunch only']
        assert 'no counter is configured' in caplog.text


if __name__ == '__main__':      # a runnable check without pytest
    import pytest
    raise SystemExit(pytest.main([__file__, '-q']))


class TestTheCounterCapIsPerService:
    """`MAX_COUNTERS` bounds the STATIONS one service runs, not the rows the
    document happens to hold. Checked on the flattened list, a site running 4
    at lunch and 4 at dinner would be refused a save with a number the editor
    never showed it."""

    def _validate(self, counters):
        from src.client.client_config import ClientConfigLoader
        ClientConfigLoader._validate_counters(                   # noqa: SLF001
            [normalize_counter(c, i) for i, c in enumerate(counters)])

    def test_four_at_each_service_is_eight_rows_and_still_fine(self):
        from src.client.client_config import MAX_COUNTERS
        n = MAX_COUNTERS - 2
        self._validate([_counter(f'L{i}', [LUNCH]) for i in range(n)]
                       + [_counter(f'D{i}', [DINNER]) for i in range(n)])

    def test_over_the_cap_within_one_service_is_refused_by_name(self):
        import pytest
        from src.client.client_config import MAX_COUNTERS
        with pytest.raises(ValueError, match=f'allowed for {LUNCH}'):
            self._validate([_counter(f'L{i}', [LUNCH])
                            for i in range(MAX_COUNTERS + 1)])

    def test_an_unsplit_list_is_refused_without_naming_a_service(self):
        """It is over the cap at every meal, and the first checked is
        breakfast — which a lunch-only site does not serve."""
        import pytest
        from src.client.client_config import MAX_COUNTERS
        with pytest.raises(ValueError) as ei:
            self._validate([_counter(f'X{i}') for i in range(MAX_COUNTERS + 1)])
        assert 'allowed.' in str(ei.value) and 'breakfast' not in str(ei.value)
