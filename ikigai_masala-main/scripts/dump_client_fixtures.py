#!/usr/bin/env python3
"""Regenerate ``tests/client_fixtures.py`` from a `clients` table export.

The fixture file is a snapshot of the live table, and the all-clients sweep is
only as honest as that snapshot: while it sat at 43 clients the live table had
56, so AT&T, Bakertilly, Citrix, Tekion CHN, ToastTab CHN, DXC, Corning Chakan
and the six NCR sites were never swept, and nine clients that WERE swept had
drifted (Citrix's whole theme map, Booking's slot counts, Clario's combo slot).

Hand-editing 600 lines of literal for each refresh is how that drift happens, so
the refresh is a command:

    python scripts/dump_client_fixtures.py --clients clients_rows.csv \\
        [--app-settings app_settings_rows.csv]

Both CSVs are the Supabase table exports. `counters`, `source_pools`,
`working_days` and `shared_categories` are JSON columns; a blank cell means the
column is unset, which is not the same as `[]` and is preserved as such.

The output is deliberately a plain Python literal — reviewable in a diff, no
parser needed at test time. Run it, read the diff, commit it.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "tests" / "client_fixtures.py"

#: Deliberate deviations from live, each with the reason it is not just drift.
#: Applied after the export is read, so a refresh cannot silently drop them.
OVERRIDES: Dict[str, Dict[str, Any]] = {
    # `working_days` is blank for every live row, so nothing in the sweep would
    # exercise the horizon filter. Quince's three-day week is the only coverage
    # of it and is kept synthetic on purpose.
    "Quince": {"working_days": ["wednesday", "thursday", "friday"]},
}

_JSON_COLS = ("counters", "source_pools", "working_days", "shared_categories")
_BOOL_COLS = ("serve_weekends", "is_launch_site")

_HEADER = '''"""Every production client configuration, for the all-clients sweep.

A snapshot of the live ``clients`` table — all {n_clients} clients / {n_counters}
counters — so ``test_all_clients_generate.py`` proves that *every* client the
tool actually serves still produces a menu, not just a representative subset.
It covers the shapes that ship: multi-counter clients, ``nonveg_main`` counts of
1-5, combo slots, single-theme counters, restricted ``source_pools``,
per-client ``item_cooldown_days`` and ``working_days``, and cities with their own
item list and ruleset (Pune, Chennai, NCR).

GENERATED — do not hand-edit. Run ``scripts/dump_client_fixtures.py`` against a
fresh `clients` export and commit the diff. Editing it by hand is how it fell
{n_stale} clients behind the live table, which meant a third of the fleet was
never swept.

Kept as a Python literal rather than a SQL dump so it is reviewable in diffs and
needs no parser. The sweep is marked ``slow``, so it runs on push-to-main and on
demand rather than on every pull request.

Caveats worth knowing when reading a green run. Everything here is the live
value except:

* ``working_days`` is blank on every live row, so Quince's three-day week is
  synthetic — kept because it is the only coverage of the horizon filter. It is
  declared in ``scripts/dump_client_fixtures.py::OVERRIDES`` so a refresh cannot
  drop it.
* L&T's ``Non Veg Lunch`` counter serves ``nonveg_main: 1`` live, while the
  client's requirement is the five-dish station (biryani + gravy + dry + kebab +
  egg). The snapshot mirrors live; the test that proves the five-dish behaviour
  raises the count itself, so it does not depend on the live row being changed.
"""

from typing import Any, Dict, List

'''


def _load_clients(path: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    with path.open(newline="") as fh:
        for raw in csv.DictReader(fh):
            row: Dict[str, Any] = {
                "name": raw["name"].strip(),
                "version": int(raw.get("version") or 1),
            }
            city = (raw.get("city") or "").strip()
            row["city"] = city
            for col in _BOOL_COLS:
                val = (raw.get(col) or "").strip().lower()
                row[col] = val in ("true", "t", "1", "yes")
            cooldown = (raw.get("item_cooldown_days") or "").strip()
            row["item_cooldown_days"] = int(cooldown) if cooldown else None
            for col in _JSON_COLS:
                blob = (raw.get(col) or "").strip()
                # A blank cell is an UNSET column, which the loader treats
                # differently from an empty list (source_pools=None means "the
                # whole city list"), so the distinction is preserved.
                row[col] = json.loads(blob) if blob else None
            row.update(OVERRIDES.get(row["name"], {}))
            out.append(row)
    out.sort(key=lambda r: r["name"].lower())
    return out


def _load_app_settings(path: Path | None) -> List[Dict[str, Any]]:
    if path is None or not path.exists():
        return []
    out = []
    with path.open(newline="") as fh:
        for raw in csv.DictReader(fh):
            val = (raw.get("value") or "").strip()
            try:
                parsed: Any = json.loads(val)
            except (ValueError, TypeError):
                parsed = val
            out.append({"key": raw["key"].strip(), "value": parsed})
    return out


def _fmt(value: Any, indent: int) -> str:
    """A stable, diff-friendly Python literal.

    Written by hand rather than via ``json.dumps`` + string replacement: the
    replacement approach missed a bare ``false`` at the top level (only ``":
    false"`` was swapped), so the generated module did not import. ``repr`` is
    correct for every scalar by construction.
    """
    pad = " " * indent
    inner = " " * (indent + 4)
    if isinstance(value, dict):
        if not value:
            return "{}"
        rows = [f"{inner}{k!r}: {_fmt(v, indent + 4)},"
                for k, v in value.items()]
        return "{\n" + "\n".join(rows) + f"\n{pad}}}"
    if isinstance(value, (list, tuple)):
        if not value:
            return "[]"
        rows = [f"{inner}{_fmt(v, indent + 4)}," for v in value]
        return "[\n" + "\n".join(rows) + f"\n{pad}]"
    return repr(value)


def render(clients: List[Dict[str, Any]],
           app_settings: List[Dict[str, Any]], n_stale: int) -> str:
    n_counters = sum(len(c.get("counters") or []) for c in clients)
    body = [_HEADER.format(n_clients=len(clients), n_counters=n_counters,
                           n_stale=n_stale)]
    body.append("CLIENTS: List[Dict[str, Any]] = [\n")
    for c in clients:
        body.append("    {\n")
        for key, val in c.items():
            body.append(f"        {key!r}: {_fmt(val, 8)},\n")
        body.append("    },\n")
    body.append("]\n\n\nAPP_SETTINGS: List[Dict[str, Any]] = [\n")
    for s in app_settings:
        body.append(f"    {{'key': {s['key']!r}, 'value': {_fmt(s['value'], 8)}}},\n")
    body.append("]\n")
    return "".join(body)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clients", required=True, type=Path,
                    help="clients table CSV export")
    ap.add_argument("--app-settings", type=Path, default=None,
                    help="app_settings table CSV export")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    clients = _load_clients(args.clients)
    settings = _load_app_settings(args.app_settings)
    if not settings:                                     # keep what is there
        import sys
        sys.path.insert(0, str(ROOT))
        try:
            from tests.client_fixtures import APP_SETTINGS as existing
            settings = [dict(s) for s in existing]
            print("app_settings: reusing the committed values (no CSV given)")
        except Exception:                                # pragma: no cover
            settings = []

    n_stale = 0
    try:
        import sys
        sys.path.insert(0, str(ROOT))
        from tests.client_fixtures import CLIENTS as before
        n_stale = max(0, len(clients) - len(before))
    except Exception:                                    # pragma: no cover
        pass

    text = render(clients, settings, n_stale)
    n_counters = sum(len(c.get("counters") or []) for c in clients)
    print(f"{len(clients)} clients / {n_counters} counters")
    if args.dry_run:
        print("[dry-run] nothing written")
        return
    TARGET.write_text(text)
    print(f"wrote {TARGET.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
