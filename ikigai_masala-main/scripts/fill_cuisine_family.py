#!/usr/bin/env python3
"""Fill `cuisine_family`, whose blanks are not neutral — they are a ban.

`ThemeSlotFilterRule.pre_filter_pool` narrows a cuisine-main slot with
`pool[pool['cuisine_family'] == target]`. A blank equals no target, so **a
blank-cuisine dish is dropped from every themed day** in `rice`, `veg_gravy`,
`veg_dry`, `starter` and `nonveg_main`. It survives only a `mix` day, and only
until the pool would empty (the rule falls back rather than starving a slot).

Four of the five city lists are 100% filled. **NCR is 62.9% blank — 1,000 rows,
613 of them in cuisine-main slots.** Every NCR client themes most or all of its
weekdays (`north`, plus a `south` Thursday at Junglee Games), so those 613 are
in practice unservable: they sit in the pool, pass every diagnostic, and are
filtered out before the solver ever sees them. That is the same defect
`ncr_cuisine_corrections.py` fixed for 24 mislabelled rows, three orders of
magnitude larger and caused by absence rather than a wrong label.

WHAT MAY BE PREDICTED, AND WHY IT IS NOT EVERYTHING

The vocabulary is north_indian / south_indian / chinese / continental / drink /
other, and the six are not equally safe to guess, because the theme filter does
not treat them equally. `_exclude_offtheme_cuisines` makes chinese and
continental dishes appear ONLY on their own theme day — so tagging an Indian
dish `continental` is strictly WORSE than leaving it blank: blank at least
survives a mix day. No NCR client runs a continental or chinese day at all.

So the vote may only ever propose **north_indian or south_indian**, and a row
carrying an `is_chinese_*` or `is_continental_*` flag is skipped outright and
reported. Those flags are not clean enough to write from either — `is_chinese_*`
agrees with `cuisine_family == chinese` on 89% of its rows and `is_continental_*`
on 94%, both under the 95% this file demands of an inference — and they are
exactly the rows where being wrong costs the most.

Welcome drinks are skipped for a different reason: the corpus genuinely
disagrees with itself (331 `drink` against 139 `north_indian` for the same
course), so there is no majority to learn. Eight NCR rows; they go to the report.

THRESHOLDS ARE MEASURED, NOT CHOSEN. Trained on 80% of the 6,849 distinct
dishes that carry a cuisine_family and scored against the held-out fifth:

    min_rows  min_agree   coverage   accuracy
           4       0.90      65.0%      95.3%
           5       0.90      63.1%      95.0%
           6       0.95      52.8%      96.5%      <- used
           8       0.85         ~72%      ~92%     (complete_ontology's globals)
          12       0.95      43.1%      96.1%

At 6/0.95 exactly ONE held-out row in 1,370 was wrongly predicted continental or
chinese; restricting the vote to the two Indian regions takes that to zero by
construction. Accuracy *within* north/south is 96.0%, and its residual error is
north↔south confusion — a regional nuance on a dish that stays servable on mix
days and on one of the two regional days, rather than a dish that disappears.

This is a separate script from `complete_ontology.py` for the same reason
`fill_item_colours.py` is: the column needs its own calibration and its own
report of what only the client can answer. Running it inside that pass would
have meant its global 8/0.85 and no value restriction.

Idempotent, monotone (a value is never overwritten, only a blank filled), and it
runs to a fixed point because a filled row is evidence for the next pass.
Leftovers go to `docs/cuisines_to_confirm.csv`.
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling scripts
from city_list import CITIES  # noqa: E402
from complete_ontology import TOKEN_STOPWORDS, distinct_dishes  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CITY_DIR = ROOT / "data" / "raw" / "city_items"
COLUMN = "cuisine_family"
REPORT = ROOT / "docs" / "cuisines_to_confirm.csv"

#: Measured on held-out data — see the module docstring.
MIN_ROWS = 6
MIN_AGREEMENT = 0.95

#: The only values an inference may propose. chinese and continental make a dish
#: appear ONLY on its own theme day, so they are never guessed; `drink` and
#: `other` have no majority to learn from.
PREDICTABLE = ("north_indian", "south_indian")

#: A row carrying one of these is theme-exclusive if the tag is right, so it is
#: never given a region by inference — it is reported instead.
EXCLUSIVE_PREFIXES = ("is_chinese", "is_continental")

#: Courses whose cuisine convention the corpus does not agree on, so nothing is
#: learned for them. `welcome_drink` splits 331 `drink` / 139 `north_indian`.
SKIP_COURSES = frozenset({"welcome_drink"})

#: A `sub_category` whose NAME states a region states it — `chicken_north_masala`
#: is a north Indian dish, `south_rice_bath` a south Indian one. This is reading
#: the field, not voting on it, so it outranks every tier below and is not held
#: to `MIN_AGREEMENT`.
#:
#: It has to be its own tier because the majority vote is CORRUPTED for exactly
#: the rows that need it most. Across the corpus `chicken_north_masala` reads
#: 46% north / 45% continental — not because the sub_category is ambiguous but
#: because Bangalore tags 53 of its own such rows `continental` (and Hyderabad,
#: seeded from it, another 53). That is the known defect in
#: `docs/pending_config_changes.md`, and it was blocking 64 NCR rows: a dish
#: whose own sub_category says "north" was being left blank, which the theme
#: filter reads as "never on a themed day". Every other region-naming
#: sub_category agrees 85-100%, and the ones that do not are the same mislabel
#: (`chicken_north_creamy`, 71%).
#:
#: Same argument `ncr_cuisine_corrections.py` used: a row that contradicts
#: itself is a data fix, not a judgement, and the retag follows the sub_category.
REGION_WORDS = (("north", "north_indian"), ("south", "south_indian"))


def region_from_sub_category(value: str) -> str:
    """The region a sub_category NAMES, or "" if it names none or both."""
    v = _norm(value)
    hits = {region for word, region in REGION_WORDS if word in v}
    return next(iter(hits)) if len(hits) == 1 else ""

MAX_PASSES = 5


def _norm(v) -> str:
    s = str(v).strip().lower()
    return "" if s in ("", "nan", "none") else s


def _tokens(name: str):
    return [t for t in _norm(name).split("_") if t and t not in TOKEN_STOPWORDS]


def _atomic_to_excel(frame, path):
    tmp = Path(path).with_name(Path(path).name + ".tmp")
    frame.to_excel(tmp, index=False)
    tmp.replace(path)


def load():
    frames = {}
    for city in CITIES:
        path = CITY_DIR / f"{city}.xlsx"
        if not path.exists():                                  # pragma: no cover
            continue
        d = pd.read_excel(path)
        d.columns = [c.strip() for c in d.columns]
        frames[city] = d
    return frames


def exclusive_mask(d: pd.DataFrame) -> pd.Series:
    """Rows whose flags say the dish belongs to a theme-exclusive cuisine."""
    cols = [c for c in d.columns if c.startswith(EXCLUSIVE_PREFIXES)]
    if not cols:
        return pd.Series(False, index=d.index)
    return d[cols].apply(pd.to_numeric, errors="coerce").fillna(0).sum(axis=1) > 0


def learn_by_dish(everything) -> dict:
    """{item: value} — the same dish, already filled in another city.

    The strongest evidence there is and the cheapest, so it is the only tier
    allowed to propose a value outside `PREDICTABLE`: this is not an inference
    about what a name suggests, it is the ontology's own answer for that exact
    dish. Only unanimous dishes count — where two cities disagree, neither is
    evidence.
    """
    seen = defaultdict(set)
    for item, value in zip(everything["item"], everything[COLUMN]):
        v = _norm(value)
        if v:
            seen[_norm(item)].add(v)
    return {k: next(iter(v)) for k, v in seen.items() if len(v) == 1}


def _agreed(tally: dict) -> dict:
    out = {}
    for key, counts in tally.items():
        total = sum(counts.values())
        value, n = counts.most_common(1)[0]
        if total >= MIN_ROWS and n / total >= MIN_AGREEMENT \
                and value in PREDICTABLE:
            out[key] = value
    return out


def learn(known: pd.DataFrame):
    """(course rules, attribute rules, token rules), each -> a region."""
    course = defaultdict(Counter)
    attr = defaultdict(Counter)
    token = defaultdict(Counter)
    for _, r in known.iterrows():
        value = _norm(r.get(COLUMN))
        ct = _norm(r.get("course_type"))
        if not value or ct in SKIP_COURSES:
            continue
        course[ct][value] += 1
        for col in ("sub_category", "key_ingredient"):
            a = _norm(r.get(col))
            if a:
                attr[(col, ct, a)][value] += 1
        for t in set(_tokens(r["item"])):
            token[(ct, t)][value] += 1
    return _agreed(course), _agreed(attr), _agreed(token)


def _from_rules(row, rules, tag):
    """(value, why) from one rule set, most specific evidence first.

    Order is by specificity: an attribute the ontology agrees about beats a word
    in the name, and a word beats the bare course. Among tokens the LAST match
    wins — Indian dish names put the form last (`paneer_butter_masala`), the
    same tie-break `complete_ontology.py` derived for its exclusive pairs.
    """
    course_rules, attr_rules, token_rules = rules
    ct = _norm(row.get("course_type"))
    for col in ("sub_category", "key_ingredient"):
        key = (col, ct, _norm(row.get(col)))
        if key[2] and key in attr_rules:
            return attr_rules[key], f"{tag}{col}"
    best = None
    for t in _tokens(row["item"]):
        if (ct, t) in token_rules:
            best = (token_rules[(ct, t)], f"{tag}token:{t}")
    if best:
        return best
    if ct in course_rules:
        return course_rules[ct], f"{tag}course_type"
    return None, None


def predict(row, own_rules, all_rules):
    """(value, why), preferring the city's OWN convention over the corpus.

    A cuisine_family reflects how a particular city cooks, so the same city's
    agreement about an attribute is better evidence than the pooled corpus —
    measured, not assumed: held out within each city the city-scoped tier scores
    97.5% against the cross-city tier's 96.5% at the same 6/0.95 threshold.

    The gap is not academic. Across the corpus `sub_category == mixed_veg_curry`
    reads 77% north (438 rows) and is correctly refused as regionless; within
    NCR its own rows read 97% north (111 rows), because Bangalore's south Indian
    cooking was diluting a North Indian city's convention. Same for `leafy_dal`
    (98% in NCR), `paneer_curry` (93%) and `mixed_veg_dry` (91%).
    """
    value, why = _from_rules(row, own_rules, "own ")
    if value:
        return value, why
    return _from_rules(row, all_rules, "")


def apply(d: pd.DataFrame, by_dish, own_rules, all_rules):
    """Return (df, filled, unresolved). Safe to call twice."""
    d = d.copy()
    filled, unresolved = [], []
    blank = d[COLUMN].map(_norm).eq("")
    exclusive = exclusive_mask(d)
    for i in d.index[blank]:
        row = d.loc[i]
        name = _norm(row["item"])
        ct = _norm(row.get("course_type"))
        value = by_dish.get(name)
        why = "same dish in another city"
        if value is None:
            # Reading the field beats every inference below, and beats the
            # exclusive-flag skip: a row whose sub_category says `north` while a
            # continental flag says otherwise is contradicting itself, and the
            # sub_category is the half that names a region.
            value = region_from_sub_category(row.get("sub_category"))
            why = "sub_category names the region"
        if not value:
            value = None
            if bool(exclusive[i]):
                unresolved.append((name, ct, "carries a chinese/continental flag"))
                continue
            if ct in SKIP_COURSES:
                unresolved.append((name, ct, "course has no agreed convention"))
                continue
            value, why = predict(row, own_rules, all_rules)
        if value is None:
            unresolved.append((name, ct, "no evidence"))
            continue
        d.at[i, COLUMN] = value
        filled.append((name, ct, value, why))
    return d, filled, unresolved


def main(dry_run: bool = False) -> int:
    frames = load()
    before = {c: int(d[COLUMN].map(_norm).eq("").sum()) for c, d in frames.items()}
    total = defaultdict(list)
    leftover = []

    # A filled row is evidence for the next pass, so run to a fixed point —
    # otherwise a second invocation would keep finding work and the "re-running
    # changes nothing" convention every script here follows would not hold.
    for pass_no in range(1, MAX_PASSES + 1):
        everything = pd.concat(frames.values(), ignore_index=True)
        known = distinct_dishes(everything)
        known = known[known[COLUMN].map(_norm) != ""]
        by_dish = learn_by_dish(everything)
        all_rules = learn(known)
        # One rule set per city as well: a city's own agreement about an
        # attribute is stronger evidence than the pooled corpus (see `predict`).
        own = {c: learn(d[d[COLUMN].map(_norm) != ""]) for c, d in frames.items()}
        print(f"pass {pass_no}: learned from {len(known)} classified dishes — "
              f"{len(by_dish)} cross-city dishes, {len(all_rules[1])} attribute "
              f"rules, {len(all_rules[2])} token rules, "
              f"{len(all_rules[0])} course rules")
        moved = 0
        leftover = []
        for city, d in frames.items():
            out, filled, unresolved = apply(d, by_dish, own[city], all_rules)
            frames[city] = out
            total[city] += filled
            moved += len(filled)
            leftover += [(city, *u) for u in unresolved]
        print(f"        {moved} filled")
        if not moved:
            break
    else:                                                      # pragma: no cover
        print(f"WARNING: still filling after {MAX_PASSES} passes")

    for city, d in frames.items():
        got = total[city]
        after = int(d[COLUMN].map(_norm).eq("").sum())
        if not got:
            print(f"[{city}] nothing to fill ({before[city]} blank)")
            continue
        print(f"[{city}] {len(got)} filled; blank {before[city]} -> {after}")
        for why, n in Counter(w for _, _, _, w in got).most_common(6):
            print(f"    {why:<34}{n}")
        for name, ct, value, why in got[:4]:
            print(f"      {name[:40]:42s} {ct:12s} -> {value}  ({why})")
        if not dry_run:
            _atomic_to_excel(d, CITY_DIR / f"{city}.xlsx")
            print(f"[{city}] wrote {city}.xlsx")

    if dry_run:
        print(f"\n[dry-run] nothing written; {len(leftover)} row(s) would be "
              f"reported")
        return 0
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["city", "item", "course_type", "why_not_filled",
                    "cuisine_family"])
        for row in sorted(leftover):
            w.writerow(list(row) + [""])
    try:
        shown = REPORT.relative_to(ROOT)
    except ValueError:                      # a test pointed REPORT elsewhere
        shown = REPORT
    print(f"\nwrote {shown} ({len(leftover)} dishes need the client)")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    sys.exit(main(dry_run=ap.parse_args().dry_run))
