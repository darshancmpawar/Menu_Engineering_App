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

# --- Part 2: top up thin pools by SHARING real dishes from a donor city -------
# Some cities carry only a handful of dishes in a category a client actually
# serves — Chennai has 2 rasam and 4 curd_side, Pune 2 curd_side. Over a
# multi-week run those slots go stale (and before the cooldown relaxation, they
# went INFEASIBLE). These are regional staples every Indian kitchen makes, so
# the fix is to share real, correctly-tagged dishes from the city that has them
# rather than invent rows: the whole 135-column row is copied verbatim, only
# item_id (reassigned past the city's max) and client (the city's pool token)
# change. Only VEG rows are shared, so an all-veg city stays all-veg.
#
# {course_type: minimum distinct dishes a city should carry}
SHARE_TARGETS = {
    "rasam": 12,
    "curd_side": 12,
    "sambar": 12,
    "soup": 10,
}

# Deeper, per-(city, category) targets for the slots a STRICT no-repeat rule
# actually has to sustain. rasam and sambar are deliberately NOT cooldown-exempt
# (unlike soup / curd_side / curd_rice / healthy_rice), so they can only be fixed
# with data. Sizing: a strict count-1 slot needs about one distinct dish per
# working day inside the cooldown window plus the week being planned
# (floor(20*5/7) + 5 = 19); 22 leaves a margin. Only categories a real client
# counter serves are listed — deepening a category a city does not serve would
# be noise, and a city that carries none of a category by design (Chennai has no
# welcome drinks) is never given one.
CITY_SHARE_TARGETS = {
    ("pune", "welcome_drink"): 22,   # Amadeus Pune serves it; city had 4
    ("pune", "bread"): 22,           # Amadeus Pune; city had 9
    ("chennai", "rasam"): 22,        # ToastTab CHN; city had 12
    ("chennai", "sambar"): 22,       # ToastTab CHN; city had 12
    ("ncr", "starter"): 22,          # Airtel Noida / Sinch NCR; city had 15
    ("ncr", "welcome_drink"): 22,    # Corning; city had 17
}
# Donor preference order per category (first city that has the dish wins).
SHARE_DONORS = ["bangalore", "chennai", "ncr", "pune"]

# A shared dish must be **doable in the target region**, so bread — the most
# regionally-locked category — is filtered by cuisine. Pune (Maharashtrian) and
# NCR (North Indian) take North breads (paratha/poori/kulcha/thepla/…), not the
# South breakfast breads (idli/dosa/adai/uttapam) or continental ones; Chennai
# and Bangalore take either. Drinks and starters travel freely.
CITY_REGION = {"pune": "north", "ncr": "north",
               "chennai": "south", "bangalore": "south"}
# `starter` joins the lock because NCR's ruleset forbids a continental starter
# (scripts/ncr_cuisine_corrections.py) — and Bangalore mislabels pakora / samosa
# / vada_pav as continental, so sharing them in imported that mislabel and broke
# the NCR correction.
REGION_LOCKED_CATEGORIES = {"bread", "starter"}

# A row carrying any of these flags is never shared. `is_plain_phulka_chapathi`
# is what Pune's R36 `plain_chapati_may_repeat` matches on, so importing a bread
# that carries it (tawa_roti, methi_roti, rava_roti, palak_roti all do) silently
# widens the staple exemption — those breads would become repeatable EVERY day
# instead of only plain chapati/phulka. Every city already has its own plain
# chapati, so nothing is lost by refusing them.
SHARE_EXCLUDE_FLAGS = {"is_plain_phulka_chapathi"}

# Individually-checked rows that must never be borrowed into another city:
#   pretzel    — cuisine_family=continental, sub_category=garlic_bread; not an
#                Indian bread slot dish.
#   tea_cake   — a cake filed under course_type=welcome_drink in the Bangalore
#                list; sharing it would propagate that mislabel.
#   a2b_juice  — named for a restaurant chain, not a dish another kitchen can act
#                on (abc_juice — apple/beetroot/carrot — is fine and is kept).
#   sambaram   — Kerala spiced buttermilk, i.e. the SAME drink as `buttermilk`
#                under a South Indian name, and it carries is_buttermilk=1.
#                Sharing it into a North city gave Pune two buttermilk rows and
#                handed NCR a Kerala name for a drink a Delhi kitchen calls
#                chaas; worse, being the fresher of the two it displaced the
#                daily `buttermilk` Amadeus Pune's logic expects. North cities
#                take the chaas variants instead.
SHARE_BLOCKLIST = {"pretzel", "tea_cake", "a2b_juice", "sambaram"}

# Repairs for rows an EARLIER, less careful sharing pass already wrote. The
# guards above stop them being shared again, but the rows are committed, so they
# must also be undone. Keyed (city, category) -> {item}.
UNSHARE = {
    # These four carry is_plain_phulka_chapathi, which Pune's R36 matches, so
    # they would have become daily-repeatable staples alongside plain chapati.
    ("pune", "bread"): {"rava_roti", "tawa_roti", "methi_roti", "palak_roti"},
    # Middle-Eastern; NCR's ruleset forbids a continental starter.
    ("ncr", "starter"): {"falafel"},
}

# pakora / samosa / vada_pav are plainly North Indian but the Bangalore list
# labels them `continental`; sharing carried that mislabel into NCR, where
# ncr_cuisine_corrections.py forbids a continental starter. They are worth
# keeping, so fix the label on the NCR copy rather than dropping the dish.
RECUISINE = {
    ("ncr", "starter"): ({"pakora", "samosa", "vada_pav"}, "north_indian"),
}

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




def _cat_mask(df, cat):
    return df["course_type"].map(_norm) == cat


# Opaque abbreviations seen in the source lists — a shared dish must be a name a
# kitchen can act on, so these are never borrowed into another city.
_ABBREV_WORDS = {"vwg", "cho", "khol", "kora", "mc", "m", "c", "vg", "sp"}


def _readable_name(n: str) -> bool:
    words = [w for w in n.split("_") if w]
    if not words:
        return False
    return all(len(w) >= 3 and w not in _ABBREV_WORDS for w in words)


def _generic_names() -> set:
    """Names `scripts/remove_generic_rows.py` deliberately deleted — rows named
    for a CATEGORY ("rasam", "sweet", "gravy") rather than a dish.

    Read from that script's own table so the two can never disagree: sharing
    must not quietly re-import a row the cleanup exists to remove, which it did
    — it put a dish literally called `rasam` back into NCR.
    """
    GENERIC_ROWS = None
    try:                       # imported as a package (tests, project root)
        from scripts.remove_generic_rows import GENERIC_ROWS
    except Exception:
        try:                   # run directly: scripts/ is sys.path[0]
            from remove_generic_rows import GENERIC_ROWS
        except Exception:  # pragma: no cover
            GENERIC_ROWS = None
    if not GENERIC_ROWS:
        raise RuntimeError(
            "cannot read GENERIC_ROWS from remove_generic_rows.py — refusing to "
            "share, since generic category rows would leak back in")
    out = set()
    for names in GENERIC_ROWS.values():
        out |= {str(n).strip().lower() for n in names}
    return out


_GENERIC = _generic_names()


def _next_id(df):
    nums = [int(m.group(1)) for s in df["item_id"].dropna().astype(str)
            for m in [re.search(r"(\d+)", s)] if m]
    return (max(nums) + 1) if nums else 1


def _mk_id(n):
    return f"MENU{n:06d}"


#: The master/source list. Blocklisted names are legitimate rows *there* (it is
#: the ontology everything else is derived from); they must simply never be
#: borrowed into another city.
MASTER_CITY = "bangalore"


def _unshare_blocklisted(dfs):
    """Drop blocklisted dishes a previous run of this script shared out.

    The blocklist is applied when *choosing* what to share, but a name can only
    be added to it after a bad share has already been written (``sambaram`` was).
    Removing it here makes the script self-healing and keeps it idempotent.
    Scoped to the non-master cities so the source list keeps its own rows.
    """
    removed = {}
    for slug, df in dfs.items():
        if slug == MASTER_CITY:
            continue
        mask = df["item"].map(_norm).isin(SHARE_BLOCKLIST)
        # Rows an earlier, less careful pass wrote: drop by (city, category).
        for (sl, cat), items in UNSHARE.items():
            if sl != slug:
                continue
            mask = mask | (df["item"].map(_norm).isin(items)
                           & (df["course_type"].map(_norm) == cat))
        if mask.any():
            removed[slug] = sorted(df.loc[mask, "item"].map(_norm))
            df = df[~mask].reset_index(drop=True)
            dfs[slug] = df
        # Correct a mislabel carried in from the donor rather than lose the dish.
        for (sl, cat), (items, cuisine) in RECUISINE.items():
            if sl != slug or "cuisine_family" not in df.columns:
                continue
            m = (df["item"].map(_norm).isin(items)
                 & (df["course_type"].map(_norm) == cat)
                 & (df["cuisine_family"].map(_norm) != cuisine))
            if m.any():
                df.loc[m, "cuisine_family"] = cuisine
                if "cuisine_family_region" in df.columns:
                    df.loc[m, "cuisine_family_region"] = cuisine
                dfs[slug] = df
    return removed


def expand(dry_run=False):
    dfs = {c: _load(c) for c in CITIES}
    unshared = _unshare_blocklisted(dfs)
    for slug, names in unshared.items():
        print(f"{slug}: removed wrongly-shared {', '.join(names)}")
    bng = dfs[MASTER_CITY]
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

    # --- Part 2: share real dishes into thin pools (rasam/curd_side/sambar/soup)
    share_summary = {}
    for slug in CITIES:
        df = dfs[slug]
        nid = _next_id(df)
        pool_value = "common" if df["client"].map(_norm).str.contains(
            "common").any() else ""
        cats = set(SHARE_TARGETS) | {c for (s, c) in CITY_SHARE_TARGETS
                                     if s == slug}
        for cat in sorted(cats):
            target = max(SHARE_TARGETS.get(cat, 0),
                         CITY_SHARE_TARGETS.get((slug, cat), 0))
            have_names = set(df[_cat_mask(df, cat)]["item"].map(_norm))
            all_names = set(df["item"].map(_norm))
            # Never invent a category a city does not serve at all (Chennai
            # carries no welcome drinks by design).
            if not have_names:
                share_summary[(slug, cat)] = []
                continue
            missing = target - len(have_names)
            if missing <= 0:
                share_summary[(slug, cat)] = []
                continue
            additions = []
            for donor in SHARE_DONORS:
                if donor == slug or len(additions) >= missing:
                    continue
                ddf = dfs[donor]
                cand = ddf[_cat_mask(ddf, cat)].copy()
                cand = cand.assign(_n=cand["item"].map(_norm))
                cand = cand[~cand["_n"].isin(all_names)]
                # Skip abbreviated/opaque names ("vwg_sambar", "m_c_sambar",
                # "cho_sambar"): a kitchen has to recognise the dish it is asked
                # to cook. Every word must be >= 3 letters and not a known
                # abbreviation; then prefer the shorter, plainer names.
                cand = cand[cand["_n"].map(_readable_name)]
                cand = cand[~cand["_n"].isin(SHARE_BLOCKLIST)]
                cand = cand[~cand["_n"].isin(_GENERIC)]
                for _f in SHARE_EXCLUDE_FLAGS:
                    if _f in cand.columns:
                        cand = cand[pd.to_numeric(
                            cand[_f], errors="coerce").fillna(0) != 1]
                # Regional fit: a North city never borrows a South/continental
                # bread, and vice versa.
                if cat in REGION_LOCKED_CATEGORIES:
                    region = CITY_REGION.get(slug)
                    if region == "north":
                        cand = cand[~cand["cuisine_family"].map(_norm).isin(
                            {"south_indian", "continental"})]
                    elif region == "south":
                        cand = cand[cand["cuisine_family"].map(_norm) != "continental"]
                cand = cand.sort_values("_n", key=lambda s: s.str.len())
                for _i, src in cand.iterrows():
                    if len(additions) >= missing:
                        break
                    if not _is_veg(src):
                        continue
                    nm = _norm(src["item"])
                    if nm in all_names:
                        continue
                    r = src.drop(labels=["_n"]).copy()
                    r["item_id"] = _mk_id(nid); nid += 1
                    if "client" in r.index:
                        r["client"] = pool_value
                    additions.append(r)
                    all_names.add(nm)
            if additions:
                df = pd.concat([df, pd.DataFrame(additions)], ignore_index=True)
                dfs[slug] = df
            share_summary[(slug, cat)] = [_norm(a["item"]) for a in additions]

    for slug in CITIES:
        print(f"\n{slug}:")
        for cat in CATEGORIES:
            adds = summary.get((slug, cat), [])
            print(f"  {cat:12s} +{len(adds)}: "
                  f"{', '.join(adds) if adds else '(already present)'}")
        for cat in sorted(set(SHARE_TARGETS) | {c for (sl, c) in CITY_SHARE_TARGETS if sl == slug}):
            adds = share_summary.get((slug, cat), [])
            if adds:
                print(f"  {cat:12s} +{len(adds)} shared: {', '.join(adds)}")
    summary.update(share_summary)

    if dry_run:
        print("\n[dry-run] no files written")
        return summary

    for slug in CITIES:
        _atomic_to_excel(dfs[slug], CITY_DIR / f"{slug}.xlsx", index=False)
    print("\nwrote 4 city workbooks")
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    expand(dry_run=args.dry_run)


def _atomic_to_excel(frame, path, **kw):
    """Write via a temp file + rename.

    `to_excel` truncates the target before streaming into it, so an
    interrupted run leaves a 0-byte workbook and the city's item list is
    gone. That happened once; it must not happen twice.
    """
    import pathlib as _pl
    p = _pl.Path(path)
    tmp = p.with_name(p.name + ".tmp")
    kw.setdefault("index", False)
    frame.to_excel(tmp, **kw)
    tmp.replace(p)
