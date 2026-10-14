"""What a counter is configured to serve, the data can actually serve.

The correction chain used to rebuild the derived artefacts and re-apply every
hand fix, and CI called into it. That chain was deleted in v2.07.03 (the five
city workbooks are the source now), and the CI step calling it has failed on
every run since — so the guarantees it carried lapsed quietly. These are the
ones worth keeping, moved to where they belong.

**One test that was written here and deleted, because it was wrong.** The
first version asserted that every category a workbook SOURCES must appear in
`ontology_categories.json`. It failed on exactly one thing: Pune's list
carries two `infused_water` dishes that Pune does not declare. Checked before
"fixing" it — **no Pune counter serves `infused_water`** (only Booking.com, in
Bangalore, serves it at all). Declaring it would have made `build_pools` raise
for every Pune plan the day a future workbook dropped a category nobody uses:
a new hard-failure mode bought to prevent a harmless surplus. The manifest
means "categories this city is EXPECTED to cover", and expectation comes from
what clients serve, not from what a workbook happens to contain. The test was
measuring the wrong thing, so it is gone rather than relaxed.

What is here instead is the invariant that actually bites, and it is the shape
of a live bug: Waters was configured with `shared_categories: ['nonveg_main']`
while its primary counter has no such slot, so zero items synced across four
counters and nothing said so.
"""

from __future__ import annotations

import json

import pytest

from src.constants import BASE_SLOT_NAMES, CONST_SLOTS, REPEATABLE_SLOTS
from src.ontology.paths import CITY_ONTOLOGY_CATEGORIES_PATH, city_required_slots
from src.ontology.repository import repository
from src.preprocessor.pool_builder import _base_slot
from tests.client_fixtures import CLIENTS

CITIES = ['Bangalore', 'Hyderabad', 'Chennai', 'Pune', 'NCR']

#: A week is five planned days. A slot running two cells needs ten distinct
#: dishes before uniqueness forces a repeat.
DAYS = 5


def _counters():
    for row in CLIENTS:
        city = row.get('city')
        if not city:
            continue
        for counter in (row.get('counters') or []):
            yield row, city, counter


@pytest.mark.parametrize('city', CITIES)
def test_every_declared_category_is_actually_there(city):
    """`build_pools` raises on this at load time; catching it here means
    finding out from a test rather than from a planner pressing Generate."""
    _df, pools = repository.menu_data(city)
    declared = set(city_required_slots(city) or ())
    empty = sorted(s for s in declared if not len(pools.get(s, ())))
    assert not empty, (
        f'{city} declares {empty} in ontology_categories.json but its '
        f'workbook yields no such dishes. Every plan for this city raises '
        f'until either the workbook or the manifest is corrected.')


def test_the_manifest_only_names_real_base_slots():
    """A typo here is note 9 in a config file: `veg_grvy` declares a slot that
    can never be satisfied, and the city stops planning with a message naming
    a slot nobody recognises."""
    raw = json.loads(CITY_ONTOLOGY_CATEGORIES_PATH.read_text())
    for city, slots in raw.items():
        if city.startswith('_'):
            continue
        unknown = sorted(set(slots) - set(BASE_SLOT_NAMES))
        assert not unknown, (
            f'{city} declares {unknown}, which are not base slots. '
            f'Known: {sorted(BASE_SLOT_NAMES)}')


def test_no_counter_is_configured_for_a_slot_its_pool_cannot_fill():
    """The invariant with teeth, over every counter of every client.

    A counter serving a slot its own narrowed pool cannot fill is not a thin
    pool to degrade around — it is a configuration that cannot produce a menu.
    Measured across the fleet at zero today, which is what makes this a guard
    rather than a wish.

    Skips what is not solved from a pool: `CONST_SLOTS` are stamped after the
    solve, and `REPEATABLE_SLOTS` may serve one dish all week by design.
    """
    skip = set(CONST_SLOTS) | set(REPEATABLE_SLOTS)
    cache, bad = {}, []
    for row, city, counter in _counters():
        key = (city, tuple(row.get('source_pools') or []))
        if key not in cache:
            cache[key] = repository.filtered_menu_data(
                city, row.get('source_pools'))[1]
        pools = cache[key]
        counts = counter.get('slot_counts') or {}
        for category in (counter.get('categories') or []):
            base = _base_slot(str(category))
            if base in skip:
                continue
            have = len(pools.get(base, ()))
            need = DAYS * int(counts.get(base, 1) or 1)
            if have < need:
                bad.append(
                    f'{row["name"]} / {counter.get("name")} ({city}): '
                    f'{base} has {have} dishes, needs {need}')
    assert not bad, (
        'these counters cannot fill a five-day week from their own pool:\n  '
        + '\n  '.join(bad))


#: Known outstanding, recorded in `docs/pending_config_changes.md` §0. Waters
#: stores `shared_categories: ['nonveg_main']` while its primary counter is
#: `Roti Veg Combo`, which has no such slot. The API refuses this combination
#: on write now, but the check only runs on a write — the stored row needs an
#: operator with database access, which no test can supply. Named here so the
#: guard below stays live for every OTHER client instead of being switched
#: off wholesale.
_SHARED_CATEGORY_KNOWN_BAD = {'Waters'}


def _shared_category_offenders():
    """`[(client, missing categories)]` — shared categories the primary cannot supply."""
    out = []
    for row in CLIENTS:
        shared = [str(s) for s in (row.get('shared_categories') or [])]
        counters = row.get('counters') or []
        if not shared or not counters:
            continue
        primary = {_base_slot(str(c))
                   for c in (counters[0].get('categories') or [])}
        missing = sorted(s for s in shared if _base_slot(s) not in primary)
        if missing:
            out.append((row['name'], missing, counters[0].get('name'),
                        sorted(primary)))
    return out


def test_a_shared_category_is_one_the_primary_counter_serves():
    """Waters' bug, as a standing guard for everyone else.

    `shared_categories` takes the dish from the PRIMARY counter and copies it
    to the others, so naming a category the primary does not serve syncs
    nothing — measured zero shared items across a four-counter site, with the
    toggle on and the category listed in the editor the whole time.
    """
    bad = [f'{name}: shares {missing}, but its primary counter ({ctr}) '
           f'serves {serves}'
           for name, missing, ctr, serves in _shared_category_offenders()
           if name not in _SHARED_CATEGORY_KNOWN_BAD]
    assert not bad, (
        'a shared category the primary counter cannot supply syncs nothing, '
        'silently:\n  ' + '\n  '.join(bad))


@pytest.mark.xfail(strict=True, reason=(
    'Waters still stores a shared category its primary counter cannot supply '
    '— pending_config_changes.md §0, needs a database edit'))
def test_the_known_bad_shared_category_is_still_broken():
    """The allowlist above cannot go stale.

    `strict=True` means this test FAILS the moment Waters is fixed, which is
    what forces the name out of `_SHARED_CATEGORY_KNOWN_BAD`. Without it, the
    exemption would outlive the bug and quietly stop guarding that client.
    """
    assert not [n for n, *_ in _shared_category_offenders()
                if n in _SHARED_CATEGORY_KNOWN_BAD]


if __name__ == '__main__':      # a runnable check without pytest
    raise SystemExit(pytest.main([__file__, '-q']))
