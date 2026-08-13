#!/usr/bin/env python3
"""Enlarge the small side-slot pools so counters don't run dry under the cooldown.

A rolling fleet sweep found four categories with pools too small to sustain a
multi-week run: ``healthy_rice``, ``dessert``, flavoured ``bread`` (flavoured
chapati) and ``starter`` — Pune had 1 healthy rice and 0 starters, Chennai 2
healthy rices, NCR 2. This script adds **7 dishes to each of those four
categories in every city** ("add 7 unique not in the dataset, preparable without
complications, into each city").

The 7 per category are a fixed, curated set of simple pan-India VEG dishes not
present in any city today — the same set goes to every city, so a region that
was missing (say) flavoured chapatis now has the same seven the others do (the
cross-city sharing is in the curation: the picks are chosen to fit North and
South alike). Each is built by cloning a plain same-category Bangalore template
row for the 135-column skeleton, then **zeroing every is_* flag** and setting
only the essentials + colour/cuisine/liquid — so a clone never inherits the
template dish's specifics (e.g. gulab_jamun's is_sugar_syrup_heavy_dessert or
gobi_65's key_ingredient=cauliflower). A row's ``client`` pool token follows the
city's convention (``common`` where the city has a common pool, blank for NCR).

Fixed set ⇒ **idempotent**: a dish already present by name is skipped, so
re-running after a re-import changes nothing. ``--dry-run`` writes nothing.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CITY_DIR = ROOT / "data" / "raw" / "city_items"
CITIES = ["bangalore", "pune", "chennai", "ncr"]
CATEGORIES = ["healthy_rice", "dessert", "bread", "starter"]

_NONVEG_FLAGS = ["is_egg_dish", "is_seafood", "is_fish_dish", "is_chicken",
                 "is_nonveg"]

# Exactly 7 curated VEG dishes per category, verified absent from every city.
# (name, item_color, cuisine_family, is_liquid_dessert)
NEW_DISHES = {
    "healthy_rice": [
        ("coriander_millet_rice", "green", "south_indian", 0),
        ("beetroot_brown_rice", "red", "north_indian", 0),
        ("mint_millet_pulao", "green", "north_indian", 0),
        ("carrot_peas_brown_rice", "orange", "north_indian", 0),
        ("tamarind_millet_rice", "brown", "south_indian", 0),
        ("curd_millet_rice", "white", "south_indian", 0),
        ("spinach_brown_rice", "green", "north_indian", 0),
    ],
    "dessert": [
        ("apple_halwa", "red", "north_indian", 0),
        ("dates_and_nuts_ladoo", "brown", "north_indian", 0),
        ("carrot_kheer", "orange", "south_indian", 1),
        ("coconut_rava_ladoo", "white", "south_indian", 0),
        ("wheat_flour_ladoo", "brown", "north_indian", 0),
        ("mixed_fruit_custard", "yellow", "continental", 1),
        ("apple_kheer", "red", "north_indian", 1),
    ],
    "bread": [  # flavoured chapatis
        ("methi_chapati", "green", "north_indian", 0),
        ("palak_chapati", "green", "north_indian", 0),
        ("beetroot_chapati", "red", "north_indian", 0),
        ("carrot_chapati", "orange", "north_indian", 0),
        ("coriander_chapati", "green", "north_indian", 0),
        ("tomato_chapati", "red", "north_indian", 0),
        ("garlic_chapati", "brown", "north_indian", 0),
    ],
    "starter": [  # all veg
        ("veg_spring_roll", "brown", "chinese", 0),
        ("hara_bhara_kabab", "green", "north_indian", 0),
        ("veg_manchurian_dry", "brown", "chinese", 0),
        ("crispy_corn", "yellow", "chinese", 0),
        ("veg_seekh_kabab", "green", "north_indian", 0),
        ("corn_spinach_kabab", "green", "north_indian", 0),
        ("beetroot_tikki", "red", "north_indian", 0),
    ],
}

# Plain same-category Bangalore rows cloned only for the 135-column skeleton.
NEW_TEMPLATE = {
    "healthy_rice": "brown_jeera_rice",
    "dessert": "gulab_jamun",
    "bread": "methi_thepla",
    "starter": "gobi_65",
}

# Essential flags a curated dish of each category carries (all other is_* zeroed).
NEW_ESSENTIAL_FLAGS = {
    "healthy_rice": {"is_rice": 1},
    "dessert": {"is_sweet": 1, "is_dessert": 1},
    "bread": {"is_bread": 1},
    "starter": {"is_veg_starter": 1},
}


def _norm(s) -> str:
    return str(s).strip().lower() if s is not None else ""


def _load(slug):
    df = pd.read_excel(CITY_DIR / f"{slug}.xlsx")
    df.columns = [c.strip() for c in df.columns]
    return df


def _is_veg(row) -> bool:
    if _norm(row.get("primary_protein")) in {
            "chicken", "mutton", "fish", "egg", "prawn", "seafood",
            "lamb", "goat", "beef", "pork"}:
        return False
    for f in _NONVEG_FLAGS:
        if f in row.index and str(row.get(f)).strip().lower() in ("1", "1.0", "true"):
            return False
    return True


_FLAVOURED_BREAD = re.compile(r"(chapat|thepla|thalipeeth|phulka)")


def _is_flavoured_chapati(name: str) -> bool:
    """A flavoured/infused chapati or thepla (not a plain chapati/phulka)."""
    n = _norm(name)
    if "thepla" in n or "thalipeeth" in n:
        return True
    return bool(_FLAVOURED_BREAD.search(n)) and n not in (
        "chapati", "plain_chapatti", "plain_chapati", "phulka",
        "plain_phulka", "roti")


def _cat_mask(df, cat):
    return df["course_type"].map(_norm) == cat


def _next_id(df):
    nums = [int(m.group(1)) for s in df["item_id"].dropna().astype(str)
            for m in [re.search(r"(\d+)", s)] if m]
    return (max(nums) + 1) if nums else 1


def _mk_id(n):
    return f"MENU{n:06d}"


def expand(dry_run=False):
    dfs = {c: _load(c) for c in CITIES}
    bng = dfs["bangalore"]
    templates = {}
    for cat, tname in NEW_TEMPLATE.items():
        sub = bng[_cat_mask(bng, cat)]
        row = sub[sub["item"].map(_norm) == _norm(tname)]
        templates[cat] = (row.iloc[0] if len(row) else sub.iloc[0]).copy()

    summary = {}
    for slug in CITIES:
        df = dfs[slug]
        nid = _next_id(df)
        pool_value = "common" if df["client"].map(_norm).str.contains(
            "common").any() else ""
        for cat in CATEGORIES:
            have = set(df[_cat_mask(df, cat)]["item"].map(_norm))
            all_names = set(df["item"].map(_norm))
            additions = []
            for name, color, cuisine, liquid in NEW_DISHES[cat]:
                nm = _norm(name)
                if nm in all_names:          # idempotent: already present
                    continue
                r = templates[cat].copy()
                for col in r.index:
                    if col.startswith("is_"):
                        r[col] = 0
                for col, val in NEW_ESSENTIAL_FLAGS[cat].items():
                    if col in r.index:
                        r[col] = val
                if "is_rule_ready" in r.index:
                    r["is_rule_ready"] = 1
                if cat == "dessert" and "is_liquid_dessert" in r.index:
                    r["is_liquid_dessert"] = int(liquid)
                r["item_id"] = _mk_id(nid); nid += 1
                r["item"] = name
                for col, val in (("client", pool_value), ("item_color", color),
                                 ("cuisine_family", cuisine),
                                 ("cuisine_family_region", cuisine),
                                 ("primary_protein", ""), ("key_ingredient", ""),
                                 ("sub_category", "")):
                    if col in r.index:
                        r[col] = val
                additions.append(r)
            if additions:
                # Accumulate into df so the NEXT category sees these rows too;
                # reassigning only dfs[slug] would let each category overwrite
                # the previous one's additions (only the last would survive).
                df = pd.concat([df, pd.DataFrame(additions)], ignore_index=True)
                dfs[slug] = df
            summary[(slug, cat)] = [_norm(a["item"]) for a in additions]

    for slug in CITIES:
        print(f"\n{slug}:")
        for cat in CATEGORIES:
            adds = summary.get((slug, cat), [])
            print(f"  {cat:12s} +{len(adds)}: "
                  f"{', '.join(adds) if adds else '(already present)'}")

    if dry_run:
        print("\n[dry-run] no files written")
        return summary

    for slug in CITIES:
        dfs[slug].to_excel(CITY_DIR / f"{slug}.xlsx", index=False)
    print("\nwrote 4 city workbooks")
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    expand(dry_run=args.dry_run)
