"""Where a pairing rule could actually change a menu, and where it could not.

A pairing is only worth a rule where the SOLVER HAS A CHOICE. Three outcomes
per (pair, counter), and only one of them is worth shipping:

  UNFULFILLABLE  the target selector matches nothing the counter can serve.
                 The rule would load, report satisfied and constrain nothing —
                 note 9's expensive failure. `diagnose()` must say so.
  INERT          every dish the target slot can hold already matches, so the
                 pair happens whatever the solver picks. A rule here is weight
                 spent on a foregone conclusion.
  GRADIENT       both sides exist and the target slot can hold non-matching
                 dishes too. The only case where an objective term moves a menu.

Pool-level: no CP-SAT, no solves, no database. It reads the five city workbooks
and the committed client rows, so it is cheap enough to re-run whenever a
workbook changes — which matters, because the work order's own counts were
taken before the corrected Bangalore and Pune lists landed.

    python scripts/pairing_opportunity.py                # every city, summary
    python scripts/pairing_opportunity.py --counters     # per client counter
    python scripts/pairing_opportunity.py --pair P1      # one pair

Selectors are resolved with `SelectorFrequencyRule`'s own parser and matcher,
not a copy: a report that disagreed with the rule it is advising would be worse
than no report.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import OrderedDict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('SUPABASE_URL', 'http://pairing-opportunity.invalid')
os.environ.setdefault('SUPABASE_KEY', 'not-used-this-script-reads-files')

from src.menu_rules.selector_frequency_rule import SelectorFrequencyRule  # noqa: E402
from src.ontology.repository import repository  # noqa: E402

CITIES = ['Bangalore', 'Hyderabad', 'Chennai', 'Pune', 'NCR']

#: The two rungs from the work order. STRONG says "make this pair if the plate
#: allows it"; PREFERRED (the `low` tier default) says "nice to have, yield to
#: variety". Carried here rather than only in the rule JSON so the tier-budget
#: guard measures the weights that actually ship — it first measured all six at
#: the default and so under-reported the mass by the two STRONG rules.
STRONG = 3_000_000
PREFERRED = 1_000_000

#: The §5 catalogue, as the rule JSON would carry it. `slots_b` lists every
#: pool a target may live in — a combo counter keeps its sambar in
#: `dal_sambar` or `sambar_rasam`, so naming only `sambar` would read as
#: UNFULFILLABLE on exactly the counters where the pair has its gradient.
PAIRS = OrderedDict([
    ('P1', {
        'name': 'poori / bhatura -> aloo or chana gravy',
        'sel_a': {'sub_category': 'poori_/_bhatura'}, 'slots_a': ['bread'],
        'sel_b': {'any_flag': ['is_aloo_gravy', 'is_chana_gravy',
                               'is_kabuli_chana_gravy', 'is_black_chana_gravy']},
        'slots_b': ['veg_gravy'], 'weight': STRONG,
    }),
    ('P2', {
        'name': 'south tiffin -> sambar',
        'sel_a': {'any_of': [
            {'flag': 'is_dosa_family'},
            {'sub_category': 'idli_/_steamed'},
            {'sub_category': 'uthappam'},
            {'sub_category': 'lentil-based_dosa_(adai/pesarattu)'},
        ]}, 'slots_a': ['bread'],
        'sel_b': {'course_type': 'sambar'},
        'slots_b': ['sambar', 'dal_sambar', 'sambar_rasam'], 'weight': STRONG,
    }),
    ('P3', {
        'name': 'tandoor bread -> rich north gravy or creamy dal',
        'sel_a': {'sub_category': 'tandoor'}, 'slots_a': ['bread'],
        'sel_b': {'any_of': [
            {'flag': 'is_paneer_gravy'},
            {'flag': 'is_black_chana_gravy'},
            {'sub_category': 'creamy_dal_(makhni/dhaba)'},
        ]},
        'slots_b': ['veg_gravy', 'dal', 'dal_sambar', 'dal_rasam'],
    }),
    ('P4', {
        'name': 'khichdi -> kadhi or raita',
        'sel_a': {'sub_category': 'north_khichdi'}, 'slots_a': ['rice'],
        'sel_b': {'any_of': [{'sub_category': 'kadhi'}, {'flag': 'is_raita'}]},
        'slots_b': ['veg_gravy', 'curd_side'],
    }),
    ('P5', {
        'name': 'biryani -> onion / cucumber salad',
        'sel_a': {'any_flag': ['is_biryani_item', 'is_nonveg_biryani']},
        'slots_a': ['rice', 'nonveg_main'],
        'sel_b': {'name_contains': ['cucumber', 'onion']}, 'slots_b': ['salad'],
    }),
    ('P6', {
        'name': 'biryani -> salan',
        'sel_a': {'any_flag': ['is_biryani_item', 'is_nonveg_biryani']},
        'slots_a': ['rice', 'nonveg_main'],
        'sel_b': {'name_contains': ['salan']}, 'slots_b': ['veg_gravy'],
    }),
])


def _matcher(sel):
    m = SelectorFrequencyRule._parse_matcher(sel)
    if m is None:
        raise SystemExit(f'selector does not parse — note 9: {sel!r}')
    return m


def _count(pools, slots, matcher):
    """(matching rows, total rows) across *slots* that this counter has."""
    hit = tot = 0
    for slot in slots:
        pool = pools.get(slot)
        if pool is None or not len(pool):
            continue
        tot += len(pool)
        # `to_dict('records')` rather than `iterrows()` — `_matches` only does
        # `row.get`, and this walks every pool of every counter.
        hit += sum(1 for r in pool.to_dict('records')
                   if SelectorFrequencyRule._matches(r, matcher))
    return hit, tot


def verdict(n_a, n_b, tot_b):
    """GRADIENT / INERT / UNFULFILLABLE / IDLE, from the two counts."""
    if n_a == 0:
        return 'IDLE'              # no trigger: the rule can never fire here
    if n_b == 0:
        return 'UNFULFILLABLE'     # trigger but no target: diagnose() must warn
    if tot_b and n_b == tot_b:
        return 'INERT'             # every candidate matches; the pair is free
    return 'GRADIENT'


def _slots_present(pools, slots):
    return [s for s in slots if s in pools and len(pools[s])]


def city_report(pair_ids):
    print('=' * 86)
    print('PAIRING OPPORTUNITY — per city workbook (the whole list, not a counter)')
    print('=' * 86)
    print(f"{'pair':5}{'city':12}{'trigger':>9}{'target':>9}{'of':>8}"
          f"{'share':>8}  verdict")
    for pid in pair_ids:
        spec = PAIRS[pid]
        ma, mb = _matcher(spec['sel_a']), _matcher(spec['sel_b'])
        for city in CITIES:
            try:
                _df, pools = repository.menu_data(city)
            except Exception as exc:                       # noqa: BLE001
                print(f'{pid:5}{city:12}  !! {type(exc).__name__}: {exc}')
                continue
            n_a, _ = _count(pools, spec['slots_a'], ma)
            n_b, tot_b = _count(pools, spec['slots_b'], mb)
            share = (100.0 * n_b / tot_b) if tot_b else 0.0
            print(f'{pid:5}{city:12}{n_a:>9}{n_b:>9}{tot_b:>8}{share:>7.1f}%  '
                  f'{verdict(n_a, n_b, tot_b)}')
        print()


def counter_report(pair_ids):
    from tests.client_fixtures import CLIENTS

    print('=' * 86)
    print('PAIRING OPPORTUNITY — per client counter (what a rule would actually meet)')
    print('=' * 86)
    tally = {pid: {'GRADIENT': 0, 'INERT': 0, 'UNFULFILLABLE': 0,
                   'IDLE': 0, 'NO SLOT': 0} for pid in pair_ids}
    for pid in pair_ids:
        spec = PAIRS[pid]
        ma, mb = _matcher(spec['sel_a']), _matcher(spec['sel_b'])
        print(f"\n--- {pid}: {spec['name']}")
        for row in CLIENTS:
            city = row.get('city')
            if not city:
                continue
            try:
                _df, pools = repository.filtered_menu_data(
                    city, row.get('source_pools'))
            except Exception:                              # noqa: BLE001
                continue
            for counter in (row.get('counters') or []):
                cats = {str(c) for c in (counter.get('categories') or [])}
                # A counter only meets the pair if it runs BOTH sides.
                has_a = [s for s in spec['slots_a'] if s in cats]
                has_b = [s for s in spec['slots_b'] if s in cats]
                if not has_a or not has_b:
                    tally[pid]['NO SLOT'] += 1
                    continue
                n_a, _ = _count(pools, _slots_present(pools, has_a), ma)
                n_b, tot_b = _count(pools, _slots_present(pools, has_b), mb)
                v = verdict(n_a, n_b, tot_b)
                tally[pid][v] += 1
                if v in ('GRADIENT', 'UNFULFILLABLE'):
                    share = (100.0 * n_b / tot_b) if tot_b else 0.0
                    print(f"    {v:14}{row['name'][:22]:24}"
                          f"{str(counter.get('name'))[:20]:22}"
                          f"trigger={n_a:<5}target={n_b}/{tot_b} ({share:.1f}%)")
    print('\n' + '=' * 86)
    print('SUMMARY — a pair with no GRADIENT counter is dropped (work order §6 phase 1 gate)')
    print('=' * 86)
    print(f"{'pair':5}{'GRADIENT':>10}{'INERT':>8}{'UNFULFIL':>10}"
          f"{'IDLE':>7}{'NO SLOT':>9}   keep?")
    for pid in pair_ids:
        t = tally[pid]
        keep = 'KEEP' if t['GRADIENT'] else 'DROP — no counter where it can move a menu'
        print(f"{pid:5}{t['GRADIENT']:>10}{t['INERT']:>8}"
              f"{t['UNFULFILLABLE']:>10}{t['IDLE']:>7}{t['NO SLOT']:>9}   {keep}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--pair', action='append', choices=list(PAIRS),
                    help='limit to one or more pairs (default: all)')
    ap.add_argument('--counters', action='store_true',
                    help='also report per client counter')
    args = ap.parse_args()
    pair_ids = args.pair or list(PAIRS)
    city_report(pair_ids)
    if args.counters:
        counter_report(pair_ids)


if __name__ == '__main__':
    main()
