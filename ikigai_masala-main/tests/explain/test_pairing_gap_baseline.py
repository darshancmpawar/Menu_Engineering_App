"""How often a real plate comes back missing a complement — the permanent baseline.

This is the measurement the pairing layer has to justify itself against. The
work order's own probe found **42 of 50 plan-days gap-free (84%)** across ten
clients in four cities, and every one of the eight gaps was "hot dish, no curd
or raita" — zero "rich dish, nothing light". Six of the eight were on counters
whose categories contain no `curd_side` and no `curd` at all.

That reading is the whole shape of the feature: a soft objective cannot reward a
dish the plate has no slot for, so the measured gaps are a counter
CONFIGURATION fact and not something the solver can fix. A pairing rule is only
worth adding where both slots exist and the solver is choosing freely.

It PRINTS rather than asserts a gap count, for the reason note 33 gives about
verdicts: the number moves with the workbooks, the cooldown and the start date,
and a test that fails when a menu legitimately changes teaches people to ignore
it. What it does assert is that every client still plans and still explains —
if this file goes red, the probe itself is broken, not the menus.

Run it with `pytest -m slow tests/explain/test_pairing_gap_baseline.py -s` to
see the table.
"""

from __future__ import annotations

import collections

import pytest

flask = pytest.importorskip("flask", reason="Flask not installed")

# The work order's sample: ten clients spanning Bangalore, Chennai, Pune and NCR.
SAMPLE = [
    'Zscaler', 'Citrix', 'Amadeus', 'Gartner', 'Corning Chakan',
    'PhonePe', 'Airtel Noida', 'Booking.com', 'Moengage', 'Huron',
]
START = '2026-11-02'
DAYS = 5
TIME_LIMIT = 40

#: Which `pairings.gaps` sentence is which kind. The detector writes prose, so
#: this groups on the two phrases it actually produces rather than on a code it
#: does not emit — see `src/explain/pairings.py`.
_KINDS = (('cooling', ('curd', 'raita', 'cooling')),
          ('light', ('light', 'rich')))


def _kind(sentence: str) -> str:
    low = str(sentence).lower()
    for name, needles in _KINDS:
        if any(n in low for n in needles):
            return name
    return 'other'


def _counter_lacks_a_cooling_slot(counter) -> bool:
    cats = {str(c) for c in (counter.get('categories') or [])}
    return not (cats & {'curd_side', 'curd'})


@pytest.mark.slow
def test_the_pairing_gap_baseline(fake_supabase, capsys):
    from api.app import app
    from tests.client_fixtures import CLIENTS

    app.config['TESTING'] = True
    rows = {c['name']: c for c in CLIENTS}
    missing = [n for n in SAMPLE if n not in rows]
    assert not missing, f'sample names no longer in the fixture: {missing}'
    # The shared fixture seeds ONE client (Rippling); these ten have to be put
    # in deliberately, the same way `test_theme_slot_pools::_solve` does it.
    fake_supabase.seed('clients', [dict(rows[n]) for n in SAMPLE])

    totals = collections.Counter()
    kinds = collections.Counter()
    per_client = []
    no_cooling_slot = []

    with app.test_client() as c:
        for name in SAMPLE:
            row = rows[name]
            for counter in (row.get('counters') or []):
                if _counter_lacks_a_cooling_slot(counter):
                    no_cooling_slot.append(f"{name} / {counter.get('name')}")

            plan = c.post('/api/v1/plan', json={
                'client_name': name, 'counter_index': 0,
                'start_date': START, 'num_days': DAYS,
                'time_limit_seconds': TIME_LIMIT})
            assert plan.status_code == 200, (name, plan.get_json())
            solution = plan.get_json()['solution']

            ex = c.post('/api/v1/explain', json={
                'client_name': name, 'counter_index': 0,
                'start_date': START, 'num_days': DAYS,
                'solution': solution})
            assert ex.status_code == 200, (name, ex.get_json())

            days = ex.get_json().get('days') or []
            clean = 0
            for day in days:
                gaps = ((day.get('pairings') or {}).get('gaps')) or []
                if not gaps:
                    clean += 1
                for g in gaps:
                    kinds[_kind(g)] += 1
            totals['days'] += len(days)
            totals['clean'] += clean
            per_client.append((name, len(days), clean, len(days) - clean))

    out = ['', '=' * 62, 'PAIRING GAP BASELINE', '=' * 62,
           f"{'client':24}{'days':>6}{'clean':>7}{'gaps':>6}"]
    for name, n, clean, gaps in per_client:
        out.append(f'{name:24}{n:>6}{clean:>7}{gaps:>6}')
    pct = (100 * totals['clean'] / totals['days']) if totals['days'] else 0
    out += ['-' * 62,
            f"{'TOTAL':24}{totals['days']:>6}{totals['clean']:>7}"
            f"{totals['days'] - totals['clean']:>6}   ({pct:.0f}% gap-free)",
            '', f'gaps by kind: {dict(kinds) or "none"}',
            '', 'counters with NO curd_side / curd slot '
                '(a cooling gap here is a config fact, not a solver one):']
    out += [f'  {s}' for s in no_cooling_slot] or ['  none']
    with capsys.disabled():
        print('\n'.join(out))

    # The only assertions: the probe ran, and every client planned and
    # explained. The gap COUNT is reported, never asserted — see the docstring.
    assert totals['days'] == len(SAMPLE) * DAYS, (
        f"expected {len(SAMPLE) * DAYS} plan-days, explained {totals['days']}")
