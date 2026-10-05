"""The editor's per-service tabs: what each one opens with, what gets stored.

Step 1 is the site. Steps 2 and 3 are the food, and they now repeat per
service, so a site can run different stations at lunch and at dinner.

Both functions here are pure — plain lists in, plain list out — so the two
decisions that matter are pinned without a browser:

  * **what a tab opens with.** Dinner must start as a copy of what lunch is
    running, not as a blank form. A site with one set of counters has not
    "configured lunch only"; it has configured both.
  * **what gets written.** Every client already carries
    `meals: [lunch, dinner]`, so tagging counters unconditionally would double
    the stored counters of every existing site on its first save and show
    "unsaved changes" to someone who opened the page and touched nothing. The
    tag is therefore written ONLY when the services really differ.
"""

from __future__ import annotations

from customisation.main import (counters_for_write, seed_counters_for,
                                service_split_note)
from src.history import DINNER, LUNCH


def _c(name, cats=('dal',), meals=None):
    c = {'name': name, 'categories': list(cats),
         'slot_counts': {s: 1 for s in cats}, 'theme_map': {'monday': 'north'}}
    if meals:
        c['meals'] = list(meals)
    return c


class TestWhatATabOpensWith:
    def test_dinner_copies_an_unsplit_site(self):
        """The common case, and the one that must not ask for the work twice."""
        loaded = [_c('Main'), _c('Chinese')]
        assert seed_counters_for(DINNER, loaded) == loaded

    def test_a_split_site_shows_each_service_its_own(self):
        loaded = [_c('Veg', meals=[LUNCH]), _c('Grill', meals=[DINNER])]
        assert [c['name'] for c in seed_counters_for(LUNCH, loaded)] == ['Veg']
        assert [c['name'] for c in seed_counters_for(DINNER, loaded)] == ['Grill']

    def test_a_half_split_site_falls_back_to_the_shared_ones(self):
        """Lunch was split out; dinner never was, so dinner is still the
        untagged set — not lunch's, and not empty."""
        loaded = [_c('Veg', meals=[LUNCH]), _c('Shared')]
        assert [c['name'] for c in seed_counters_for(DINNER, loaded)] == ['Shared']

    def test_an_empty_client_gives_an_empty_seed_not_a_crash(self):
        assert seed_counters_for(LUNCH, []) == []


class TestWhatGetsStored:
    def test_identical_services_write_one_untagged_list(self):
        """The whole point: an existing site that changes nothing stores
        exactly what it stored before, so nothing reads as an edit."""
        both = [_c('Main'), _c('Chinese')]
        out = counters_for_write({LUNCH: both, DINNER: [dict(c) for c in both]})
        assert out == both
        assert not any('meals' in c for c in out)

    def test_one_service_writes_one_untagged_list(self):
        assert counters_for_write({LUNCH: [_c('Main')]}) == [_c('Main')]

    def test_services_that_differ_are_tagged_and_concatenated(self):
        out = counters_for_write({LUNCH: [_c('Veg')],
                                  DINNER: [_c('Grill'), _c('Tandoor')]})
        assert [(c['name'], c['meals']) for c in out] == [
            ('Veg', [LUNCH]), ('Grill', [DINNER]), ('Tandoor', [DINNER])]

    def test_a_site_that_stops_differing_drops_its_tags(self):
        """Make dinner match lunch again and the split must UNDO, or the
        client keeps paying for a distinction it no longer has."""
        same = [_c('Main', meals=[LUNCH])]
        out = counters_for_write({LUNCH: same, DINNER: [_c('Main', meals=[DINNER])]})
        assert out == [_c('Main')] and not any('meals' in c for c in out)

    def test_a_difference_in_categories_counts_as_different(self):
        out = counters_for_write({LUNCH: [_c('Main', ('dal',))],
                                  DINNER: [_c('Main', ('dal', 'rice'))]})
        assert len(out) == 2 and all('meals' in c for c in out)

    def test_nothing_in_nothing_out(self):
        assert counters_for_write({}) == []


if __name__ == '__main__':      # a runnable check without pytest
    import pytest
    raise SystemExit(pytest.main([__file__, '-q']))


class TestTheScreenSaysWhichItIs:
    """Two tabs look the same whether dinner is its own setup or a copy of
    lunch nobody has touched — and that difference decides whether editing
    Dinner changes lunch. It matters most on an existing client, which is the
    one case where the answer is not obvious from having just typed it."""

    def test_an_unsplit_site_is_told_the_services_share(self):
        note = service_split_note([_c('Main'), _c('Chinese')], [LUNCH, DINNER])
        assert 'share one setup' in note

    def test_a_split_site_is_told_which_are_separate(self):
        note = service_split_note([_c('Veg', meals=[LUNCH]),
                                   _c('Grill', meals=[DINNER])], [LUNCH, DINNER])
        assert 'Lunch and Dinner are configured separately' in note

    def test_it_says_how_to_undo_a_split(self):
        note = service_split_note([_c('Veg', meals=[LUNCH])], [LUNCH, DINNER])
        assert 'identical again' in note

    def test_one_service_says_nothing(self):
        """No tabs are drawn, so there is nothing to explain."""
        assert service_split_note([_c('Main')], [LUNCH]) == ""
