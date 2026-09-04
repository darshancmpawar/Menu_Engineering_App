#!/usr/bin/env python3
"""Generate a menu for every client counter and report which ones fail.

Two modes, because they answer different questions:

**rolling** (default) — plan a block, SAVE it, plan the next, until the target
number of service days is covered. This is how the product runs: the planner UI
generates a week, the operator saves it, and the next week is planned against
that history. It is the mode that exercises the item cooldown, the freshness
objective and the cross-week cadence rules, because those only do anything once
there is history to read.

**single** — one request for the whole horizon. Useful as a contrast, and NOT
the supported way to plan five weeks: `unique_items` is hard, so a count-1 slot
needs one distinct dish per day of the horizon and few categories carry 25.
A failure here is usually that arithmetic, not a broken config.

Multi-counter clients are swept the way the planner drives them: the primary
counter is solved first and its dishes for the client's `shared_categories` are
passed to the later counters as `shared_items` (note 22), so a counter that
fails only because it was solved in isolation is not reported as a failure.

Reads the committed `tests/client_fixtures.py` snapshot rather than a live
database, so the result is reproducible and reviewable in a PR.

Usage:
    python scripts/sweep_menu_generation.py [--days 25] [--mode rolling|single]
                                            [--start 2026-09-07] [--block 5]
                                            [--time-limit 90] [--out FILE.md]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
import time
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

warnings.filterwarnings("ignore")


def _boot(rows):
    """A Flask test client wired to an in-memory database seeded with *rows*."""
    from tests.fake_supabase import FakeSupabase
    import src.db as db_mod

    db_mod._sb_client = FakeSupabase(seed={
        "clients": rows, "app_settings": [],
        "menu_history": [], "week_signatures": [],
    })
    import api.app as api_app
    api_app._client_loader = None
    api_app.reset_caches()
    api_app.app.config["TESTING"] = True
    return api_app


def _post(api_app, path, body):
    from api.rate_limit import reset_for_tests
    reset_for_tests()
    return api_app.app.test_client().post(path, json=body)


def _reason(resp, body):
    """The most useful one-line explanation of a non-200."""
    errs = [d for d in (body.get("rule_diagnostics") or [])
            if str(d.get("severity")).lower() == "error"]
    if errs:
        e = errs[0]
        return f"{e.get('rule') or '?'}: {str(e.get('message') or '')[:200]}"
    return str(body.get("error") or f"HTTP {resp.status_code}")[:200]


def _shared_for(api_app, client_name):
    """The client's shared base slots, as `/client-config` reports them."""
    r = api_app.app.test_client().get(f"/api/v1/client-config/{client_name}")
    cfg = r.get_json() or {}
    return (cfg.get("shared_categories") or [],
            set(cfg.get("shared_categories_excluded_counters") or []))


def sweep_client(api_app, row, days, mode, start, block, time_limit):
    """Return one record per counter for a single client.

    Block-major, not counter-major, for two reasons. It is how one Generate
    click actually runs — every counter is solved for the same dates, the
    primary first so its `shared_items` can be passed to the rest — and it
    solves the primary ONCE per block instead of once per sibling counter,
    which on a six-counter site is five solves saved per block.
    """
    from ui.formatters import shared_items_from_solution

    name = row["name"]
    counters = [c.get("name") or f"Counter {i + 1}"
                for i, c in enumerate(row["counters"])]
    shared_cats, excluded = _shared_for(api_app, name)
    blocks = ([(start, days)] if mode == "single"
              else _rolling_blocks(start, days, block))

    served = {i: 0 for i in range(len(counters))}
    failed: dict = {}
    secs = {i: 0.0 for i in range(len(counters))}

    for b_start, b_days in blocks:
        shared_items, saved = [], []
        for idx, cname in enumerate(counters):
            if idx in failed:
                continue                    # a counter that broke stays broken
            body = {"client_name": name, "start_date": b_start.isoformat(),
                    "num_days": b_days, "time_limit": time_limit,
                    "counter_index": idx}
            if idx > 0 and shared_items and cname not in excluded:
                body["shared_items"] = shared_items
            t = time.time()
            resp = _post(api_app, "/api/v1/plan", body)
            secs[idx] += time.time() - t
            data = resp.get_json() or {}
            if resp.status_code != 200:
                failed[idx] = (b_start, _reason(resp, data))
                continue
            sol = data.get("solution") or {}
            served[idx] += sum(1 for v in sol.values() if (v.get("items") or {}))
            if idx == 0 and shared_cats:
                shared_items = shared_items_from_solution(sol, shared_cats)
            saved.append({"name": cname, "week_plan": sol})
        # Save the whole block at once, the way the planner's single Save does,
        # so the next block's cooldown and freshness read every counter.
        if mode == "rolling" and saved:
            _post(api_app, "/api/v1/save", {
                "client_name": name, "week_start": b_start.isoformat(),
                "counters": saved})

    return [{
        "client": name, "city": row.get("city"), "counter": cname,
        "index": idx, "pass": idx not in failed, "days_served": served[idx],
        "failed_block": failed[idx][0].isoformat() if idx in failed else None,
        "reason": failed[idx][1] if idx in failed else "",
        "secs": round(secs[idx], 1),
    } for idx, cname in enumerate(counters)]


def _rolling_blocks(start, days, block):
    """`days` service days as consecutive blocks of at most `block` each."""
    out, remaining, cursor = [], days, start
    while remaining > 0:
        n = min(block, remaining)
        out.append((cursor, n))
        # Advance a calendar week per five-weekday block so the next block
        # starts on the same weekday, which is how the planner is driven.
        cursor = cursor + dt.timedelta(days=7 * ((n + 4) // 5))
        remaining -= n
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=int, default=25)
    ap.add_argument("--mode", choices=("rolling", "single"), default="rolling")
    ap.add_argument("--start", default="2026-09-07")
    ap.add_argument("--block", type=int, default=5)
    ap.add_argument("--time-limit", type=int, default=90)
    ap.add_argument("--out", default="")
    ap.add_argument("--only", default="", help="comma-separated client names")
    args = ap.parse_args(argv)

    logging.disable(logging.WARNING)
    from tests.client_fixtures import CLIENTS
    rows = [dict(c) for c in CLIENTS]
    if args.only:
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}
        rows = [r for r in rows if r["name"] in wanted]

    api_app = _boot(rows)
    start = dt.date.fromisoformat(args.start)

    records, t0 = [], time.time()
    for row in rows:
        for rec in sweep_client(api_app, row, args.days, args.mode,
                                start, args.block, args.time_limit):
            records.append(rec)
            flag = "PASS" if rec["pass"] else "FAIL"
            print(f"{flag}  {rec['client'][:24]:26s} {rec['counter'][:18]:20s} "
                  f"{rec['days_served']:3d}d {rec['secs']:6.1f}s {rec['reason'][:70]}",
                  flush=True)

    ok = sum(1 for r in records if r["pass"])
    clients_ok = len({r["client"] for r in records
                      if all(x["pass"] for x in records if x["client"] == r["client"])})
    print(f"\n{ok}/{len(records)} counters pass, "
          f"{clients_ok}/{len({r['client'] for r in records})} clients fully pass "
          f"({round(time.time()-t0)}s)")

    if args.out:
        Path(args.out).write_text(json.dumps(records, indent=1), encoding="utf-8")
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
