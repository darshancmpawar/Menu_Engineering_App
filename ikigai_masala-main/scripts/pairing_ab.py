"""A/B a pairing rule: solve the same clients and dates with it off, then on.

The work order's phase-4 gate, and the only thing that decides whether a
pairing is kept. It is allowed to say "do nothing": a rule that moves no menu
is dropped (YAGNI), and a rule that costs an INFEASIBLE or a new relaxation is
removed rather than tuned around.

Both arms solve the same client, the same dates and the SAME SEED
(`SolverConfig.seed` defaults to 7 and nothing here changes it), so a
difference between them is the rule and not the sampler. The OFF arm is the ON
arm with the rule filtered out of the loaded list by name — not a second config
file, which could drift.

    python scripts/pairing_ab.py pair_poori_with_aloo_or_chana
    python scripts/pairing_ab.py <rule> --clients 12 --days 5

What it reports, per the gate:

  pair satisfied   trigger days where the target is also on the plate.
                   The rule's reason to exist; the proposed bar is +20 points.
  INFEASIBLE       must be 0. A soft term cannot change feasibility, so any
                   non-zero here is a finding about the solver, not the rule.
  relaxations      must not increase.
  menu change      cells that differ between the arms. Zero means the rule
                   changes nothing and is dropped.
  distinct dishes  a variety proxy: the rule must not buy a pair by repeating.

**The NOISE FLOOR is measured first and printed beside the result, because
without it the menu-change row is unreadable.** This solver does not reproduce
its own output: the same client, the same date, the same config and the same
seed solved twice differ in ~40% of cells, with `num_workers=1` no better than
4. So a rule that changes 20% of cells has changed nothing — it is half the
noise. Any menu-change figure at or below the floor is reported as NOISE rather
than as an effect, and the rule's verdict rests on the trigger/pair rates, which
are rates over many days rather than a diff of two plans.
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('SUPABASE_URL', 'http://pairing-ab.invalid')
os.environ.setdefault('SUPABASE_KEY', 'not-used')

START_DATES = ['2026-11-02', '2026-11-09', '2026-11-16']


def _install_fake_db():
    from tests import client_fixtures as cf
    from tests.fake_supabase import FakeSupabase
    import src.db as dbmod

    fake = FakeSupabase({
        'clients': [dict(c) for c in cf.CLIENTS],
        'app_settings': list(getattr(cf, 'APP_SETTINGS', [])),
        'menu_history': [], 'week_signatures': [],
    })
    dbmod._client = fake
    dbmod._sb_client = fake
    dbmod.get_supabase = lambda: fake
    return cf.CLIENTS


def _strip(name):
    from src.solver._helpers import strip_color_suffix
    return strip_color_suffix(str(name or ''))


def _day_hits(day_items, rows_by_name, matcher, slots):
    """Does any cell of *slots* on this day match *matcher*?"""
    from src.menu_rules.selector_frequency_rule import SelectorFrequencyRule
    for slot_id, val in (day_items or {}).items():
        if slot_id.split('__')[0] not in slots:
            continue
        name = _strip(val if isinstance(val, str) else (val or {}).get('name'))
        row = rows_by_name.get(name)
        if row is not None and SelectorFrequencyRule._matches(row, matcher):
            return True
    return False


def _solve(client_name, row, cfg, start, days, drop_rule=None):
    """One arm. Returns (week_plan, relaxation_count) or (None, reason)."""
    from src.application.solve_inputs import prepare_solver_inputs
    from src.solver.menu_solver import MenuSolver
    from src.menu_rules.relaxations import RelaxationCapture

    inp = prepare_solver_inputs(
        {'client_name': client_name, 'num_days': days,
         'start_date': start.isoformat()},
        cfg, client_name=client_name, row=row, start_date=start,
        num_days=days, time_limit=30, worker_count=lambda: 4)
    rules = [r for r in inp.rules if getattr(r, 'name', '') != drop_rule]
    try:
        with RelaxationCapture() as cap:
            plan, _dates = MenuSolver(
                inp.pools, inp.cfg, menu_rules=rules,
                banned_by_date=inp.banned, ricebread_ban_day=inp.rb_ban,
                recent_sigs=inp.recent_sigs, skip_cells=inp.skip_cells,
                recency_by_item=inp.recency_by_item).solve()
        return plan, len(cap.records)
    except Exception as exc:                                   # noqa: BLE001
        return None, f'{type(exc).__name__}'


def pct_(n, d):
    return f'{100.0 * n / d:.1f}%' if d else 'n/a'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('rule', help='the rule name to A/B, e.g. pair_poori_with_aloo_or_chana')
    ap.add_argument('--clients', type=int, default=10)
    ap.add_argument('--days', type=int, default=5)
    ap.add_argument('--quiet', action='store_true')
    ap.add_argument('--dates', type=int, default=len(START_DATES),
                    help='how many of the start dates to use (smoke runs)')
    args = ap.parse_args()
    dates = START_DATES[:max(1, args.dates)]
    if args.quiet:
        logging.disable(logging.WARNING)

    CLIENTS = _install_fake_db()
    import api.app as app
    from src.menu_rules.menu_rule_loader import MenuRuleLoader
    from src.ontology.repository import repository

    loader = app._get_client_loader()

    # Which cities carry the rule, and what it looks for.
    spec = {}
    for city in ('Bangalore', 'Hyderabad', 'Chennai', 'Pune', 'NCR'):
        for r in MenuRuleLoader().load_for_city(city):
            if getattr(r, 'name', '') == args.rule:
                spec[city] = r
    if not spec:
        raise SystemExit(f'{args.rule!r} is in no city ruleset')
    any_rule = next(iter(spec.values()))
    slots_a, slots_b = set(any_rule.base_slot_a), set(any_rule.base_slot_b)
    print(f'{args.rule}\n  cities carrying it: {sorted(spec)}'
          f'\n  trigger slots {sorted(slots_a)} -> target slots {sorted(slots_b)}')

    # Clients in those cities whose PRIMARY counter runs both sides.
    picked = []
    for row in CLIENTS:
        if row.get('city') not in spec or not (row.get('counters') or []):
            continue
        cats = {str(c) for c in (row['counters'][0].get('categories') or [])}
        if (cats & slots_a) and (cats & slots_b):
            picked.append(row)
        if len(picked) >= args.clients:
            break
    print(f'  clients x dates: {len(picked)} x {len(dates)}\n')

    noise_changed = noise_cells = 0
    tot = {'trig_off': 0, 'pair_off': 0, 'trig_on': 0, 'pair_on': 0,
           'infeas_off': 0, 'infeas_on': 0, 'relax_off': 0, 'relax_on': 0,
           'cells': 0, 'changed': 0, 'dishes_off': set(), 'dishes_on': set()}

    # The noise floor: the SAME arm solved twice. Everything the menu-change
    # row claims has to clear this to mean anything.
    if picked:
        _n = picked[0]['name']
        _cfg = loader.get_client_configs_from_row(_n, picked[0])[0][1]
        _d = dt.date.fromisoformat(dates[0])
        _a, _ = _solve(_n, picked[0], _cfg, _d, args.days, drop_rule=args.rule)
        _b, _ = _solve(_n, picked[0], _cfg, _d, args.days, drop_rule=args.rule)
        if _a and _b:
            for _k in set(_a) & set(_b):
                _ia = _a[_k].get('items', _a[_k]); _ib = _b[_k].get('items', _b[_k])
                for _sid in set(_ia) | set(_ib):
                    noise_cells += 1
                    if _strip(str(_ia.get(_sid))) != _strip(str(_ib.get(_sid))):
                        noise_changed += 1
        print(f'  noise floor (same arm solved twice): '
              f'{noise_changed} of {noise_cells} cells '
              f'({pct_(noise_changed, noise_cells)})\n')

    for row in picked:
        name = row['name']
        rule = spec[row['city']]
        df, _pools = repository.filtered_menu_data(row['city'], row.get('source_pools'))
        rows_by_name = {str(r['item']): r for _i, r in df.iterrows()}
        cfg = loader.get_client_configs_from_row(name, row)[0][1]
        for ds in dates:
            start = dt.date.fromisoformat(ds)
            for arm, drop in (('off', args.rule), ('on', None)):
                plan, relax = _solve(name, row, cfg, start, args.days, drop_rule=drop)
                if plan is None:
                    tot[f'infeas_{arm}'] += 1
                    continue
                tot[f'relax_{arm}'] += relax
                for d, entry in plan.items():
                    items = entry.get('items') if isinstance(entry, dict) and 'items' in entry else entry
                    if _day_hits(items, rows_by_name, rule._sel_a, slots_a):
                        tot[f'trig_{arm}'] += 1
                        if _day_hits(items, rows_by_name, rule._sel_b, slots_b):
                            tot[f'pair_{arm}'] += 1
                    for sid, v in (items or {}).items():
                        tot[f'dishes_{arm}'].add(_strip(
                            v if isinstance(v, str) else (v or {}).get('name')))
            # menu change: same client+date, both arms
            a, _ = _solve(name, row, cfg, start, args.days, drop_rule=args.rule)
            b, _ = _solve(name, row, cfg, start, args.days, drop_rule=None)
            if a and b:
                for d in set(a) & set(b):
                    ia = a[d].get('items', a[d]); ib = b[d].get('items', b[d])
                    for sid in set(ia) | set(ib):
                        tot['cells'] += 1
                        if _strip(str(ia.get(sid))) != _strip(str(ib.get(sid))):
                            tot['changed'] += 1

    print('=' * 70)
    print(f"{'metric':34}{'OFF':>13}{'ON':>13}   gate")
    print('-' * 70)
    print(f"{'trigger days':34}{tot['trig_off']:>13}{tot['trig_on']:>13}")
    print(f"{'  of which paired':34}"
          f"{pct_(tot['pair_off'], tot['trig_off']):>13}"
          f"{pct_(tot['pair_on'], tot['trig_on']):>13}   +20 points")
    print(f"{'INFEASIBLE solves':34}{tot['infeas_off']:>13}{tot['infeas_on']:>13}   must be 0")
    print(f"{'relaxations':34}{tot['relax_off']:>13}{tot['relax_on']:>13}   must not rise")
    print(f"{'distinct dishes served':34}{len(tot['dishes_off']):>13}{len(tot['dishes_on']):>13}   no worse")
    _rate = (tot['changed'] / tot['cells']) if tot['cells'] else 0
    _floor = (noise_changed / noise_cells) if noise_cells else 0
    _verdict = 'NOISE (at or under the floor)' if _rate <= _floor else 'above the floor'
    print(f"{'menu change (cells differing)':34}"
          f"{tot['changed']:>13} of {tot['cells']}   {pct_(tot['changed'], tot['cells'])}"
          f" vs floor {pct_(noise_changed, noise_cells)} -> {_verdict}")
    print('=' * 70)
    if tot['trig_off'] == 0 and tot['trig_on'] == 0:
        print('VERDICT: the trigger never appeared. The rule had nothing to act on\n'
              '         in this sample — widen it or drop the rule (YAGNI).')


if __name__ == '__main__':
    main()
