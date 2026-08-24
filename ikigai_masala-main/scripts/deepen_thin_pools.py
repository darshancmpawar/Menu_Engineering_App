#!/usr/bin/env python3
"""Deepen the three pools a client rule asks more of than the city list holds.

Each of these was found by a rule *relaxing*: `min`/`exact` caps itself to what
the pool can supply and `diagnose()` reports the shortfall, so nothing failed —
the menu was just thinner than the client asked for, which is the failure mode
worth chasing because nothing goes red.

1. **Chennai Chinese veg gravies, 1 → 5.** Chennai carried exactly one
   (`paneer_manchurian`), so a client with a Chinese day could satisfy "a Chinese
   gravy on Tuesday" on one Tuesday per 20-day cooldown window and on none of the
   others. Copied from Bangalore rather than invented: the four chosen are the
   canteen standards, and cloning the row keeps the 134-column schema and every
   attribute the Bangalore master already carries.
2. **Pune chaat starters, 4 → 8.** Corning Chakan serves a chaat starter every
   Thursday, and four dishes is exactly four Thursdays inside the cooldown window
   with nothing spare. The four added are Maharashtra street food (ragda pattice
   above all), so they belong on a Pune list rather than being borrowed for the
   count.
3. **Pune leafy veg dries, 5 → 9.** Corning Chakan wants a leafy dry TWICE a
   week, which needs about eight distinct dishes across the cooldown window, and
   Pune's five were three fenugreek dishes plus two mixed ones. These four are
   new rows, not copies — a `<green> chi bhaji` is the everyday Maharashtrian
   preparation (greens, garlic, a little besan or peanut) and none of the four
   greens existed in any city list. Each uses a `key_ingredient` the ontology
   already carries, so `attribute_grouping` and `ingredient_ban` can see them.

A copied row keeps the source's attributes and takes a fresh `item_id` past the
target city's maximum; `client` follows the city's convention (`common` for Pune
and Chennai). A new row is cloned from a same-category template in the target
city, so it inherits the schema, with every `is_*` flag zeroed and only the
essentials set — otherwise a template's `is_deep_fried` or `is_premium` leaks
into a dish that is neither.

Idempotent (fixed sets, skip by name); re-run after any re-import.
`tests/data/test_deepen_thin_pools.py`.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CITY_DIR = ROOT / "data" / "raw" / "city_items"

#: (target city, source city, course_type, [dish names]) — cloned verbatim.
COPIES = [
    ("chennai", "bangalore", "veg_gravy", [
        # The four a canteen actually cooks, and four distinct bases so the slot
        # has variety rather than four manchurians.
        "veg_manchurian_gravy",        # brown, mixed vegetables
        "chilli_paneer_gravy",         # red, paneer
        "hot_garlic_veg_gravy",        # brown, mixed vegetables
        "schezwan_mixed_veg_gravy",    # red, mixed vegetables
    ]),
    ("pune", "bangalore", "starter", [
        "ragada_patties_chaat",        # ragda pattice — the Maharashtrian chaat
        "masala_puri_chaat",
        "dahi_papdi_chaat",
        "dahi_bhalla_chaat",
    ]),
]

#: New dishes, per (city, course_type). `template` names a same-category row in
#: the target city to clone the 134-column skeleton from; every `is_*` flag is
#: zeroed and only these fields are written on top.
NEW_DISHES: List[Dict[str, Any]] = [
    {
        "city": "pune", "course_type": "veg_dry", "template": "methi_shengdana",
        "dishes": [
            # Spinach with a garlic tempering. `palak` is spelled `spinach` in
            # the key_ingredient vocabulary, which is what the rules select on.
            {"item": "palak_chi_bhaji", "key_ingredient": "spinach"},
            # Dill greens. `shepu` is the Marathi name and the ingredient
            # dictionary already maps it to `dill`.
            {"item": "shepu_chi_bhaji", "key_ingredient": "dill"},
            # Red amaranth (lal math) — a Pune market staple with no ontology
            # ingredient of its own, so it takes the generic `leafy_greens`.
            {"item": "math_chi_bhaji", "key_ingredient": "leafy_greens"},
            # Radish greens, cooked down with the same tempering.
            {"item": "mulyachi_bhaji", "key_ingredient": "leafy_greens"},
        ],
        # Shared by all four: a leafy green dry sabzi, no region of its own in
        # the vocabulary (Maharashtrian food files as north_indian throughout
        # this ontology — see dessert_cuisine_corrections.py).
        "common": {
            "item_color": "green",
            "cuisine_family": "north_indian",
            "sub_category": "",
            "primary_protein": "",
        },
        "flags": {"is_leafy_based_dish": 1, "is_veg_dry": 1},
    },
]

#: Pool token by city, matching each city's own convention.
CLIENT_POOL = {"pune": "common", "chennai": "common", "bangalore": "common",
               "ncr": ""}


def _atomic_to_excel(frame, path, **kw):
    """Write via a temp file + rename: `to_excel` truncates the target before
    streaming into it, so an interrupted run leaves a 0-byte workbook."""
    p = Path(path)
    tmp = p.with_name(p.name + ".tmp")
    kw.setdefault("index", False)
    frame.to_excel(tmp, **kw)
    tmp.replace(p)


def _names(df) -> set:
    return set(df["item"].astype(str).str.strip().str.lower())


def _next_id(df) -> int:
    ids = pd.to_numeric(df.get("item_id"), errors="coerce")
    return int(ids.max()) + 1 if ids is not None and ids.notna().any() else 1


def _blank_flags(row: pd.Series) -> pd.Series:
    row = row.copy()
    for col in row.index:
        if str(col).startswith("is_"):
            row[col] = 0
    return row


def copy_rows(target: pd.DataFrame, source: pd.DataFrame, course: str,
              wanted: List[str], city: str):
    """Clone *wanted* rows of *course* from *source*. Returns (df, added)."""
    have = _names(target)
    src_names = source["item"].astype(str).str.strip().str.lower()
    src_course = source["course_type"].astype(str).str.strip().str.lower()
    added, rows = [], []
    nid = _next_id(target)
    for name in wanted:
        key = name.strip().lower()
        if key in have:
            continue
        hit = source[src_names.eq(key) & src_course.eq(course)]
        if hit.empty:
            print(f"    ! {name} is not a {course} in the source list — skipped")
            continue
        row = hit.iloc[0].copy()
        row["item_id"] = nid
        nid += 1
        if "client" in row.index:
            row["client"] = CLIENT_POOL.get(city, "common")
        rows.append(row)
        added.append(name)
        have.add(key)
    if not rows:
        return target, added
    out = pd.concat([target, pd.DataFrame(rows)], ignore_index=True)
    return out[target.columns], added


def add_new(target: pd.DataFrame, spec: Dict[str, Any], city: str):
    """Build new rows from a template row in the same city. (df, added)."""
    have = _names(target)
    names = target["item"].astype(str).str.strip().str.lower()
    tmpl_hit = target[names.eq(spec["template"].strip().lower())]
    if tmpl_hit.empty:                                   # pragma: no cover
        print(f"    ! template {spec['template']} is missing — skipped")
        return target, []
    template = tmpl_hit.iloc[0]
    added, rows = [], []
    nid = _next_id(target)
    for dish in spec["dishes"]:
        key = dish["item"].strip().lower()
        if key in have:
            continue
        row = _blank_flags(template)
        row["item_id"] = nid
        nid += 1
        row["course_type"] = spec["course_type"]
        for field, value in (spec.get("common") or {}).items():
            row[field] = value
        for field, value in dish.items():
            row[field] = value
        for flag, value in (spec.get("flags") or {}).items():
            if flag in row.index:
                row[flag] = value
        if "client" in row.index:
            row["client"] = CLIENT_POOL.get(city, "common")
        rows.append(row)
        added.append(dish["item"])
        have.add(key)
    if not rows:
        return target, []
    out = pd.concat([target, pd.DataFrame(rows)], ignore_index=True)
    return out[target.columns], added


def main(dry_run: bool = False) -> int:
    frames: Dict[str, pd.DataFrame] = {}
    touched: set = set()

    def load(city: str) -> pd.DataFrame:
        if city not in frames:
            df = pd.read_excel(CITY_DIR / f"{city}.xlsx")
            df.columns = [c.strip() for c in df.columns]
            frames[city] = df
        return frames[city]

    for city, src_city, course, wanted in COPIES:
        target, source = load(city), load(src_city)
        out, added = copy_rows(target, source, course, wanted, city)
        n_now = int(out["course_type"].astype(str).str.lower().eq(course).sum())
        if added:
            frames[city] = out
            touched.add(city)
            print(f"[{city}] {course}: +{len(added)} from {src_city} "
                  f"({', '.join(added)}) -> {n_now} rows")
        else:
            print(f"[{city}] {course}: already present ({n_now} rows)")

    for spec in NEW_DISHES:
        city = spec["city"]
        out, added = add_new(load(city), spec, city)
        if added:
            frames[city] = out
            touched.add(city)
            print(f"[{city}] {spec['course_type']}: +{len(added)} new "
                  f"({', '.join(added)})")
        else:
            print(f"[{city}] {spec['course_type']}: new dishes already present")

    if not touched:
        print("\nnothing to add — every pool is already deep enough")
        return 0
    for city in sorted(touched):
        if dry_run:
            continue
        _atomic_to_excel(frames[city], CITY_DIR / f"{city}.xlsx")
        print(f"[{city}] wrote {city}.xlsx ({len(frames[city])} rows)")
    if dry_run:
        print("[dry-run] nothing written")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    sys.exit(main(dry_run=ap.parse_args().dry_run))
