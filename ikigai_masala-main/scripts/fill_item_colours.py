#!/usr/bin/env python3
"""Fill `item_color` where the evidence is strong, and report what is left.

`MenuSolver._add_color_constraints` is the rule that keeps a day's plate from
being five shades of brown, and it reasons entirely on `item_color`. A row with
a blank colour is not counted as a wrong colour — it is **not counted at all**,
so it silently satisfies nothing and constrains nothing. After five client menu
imports, 30% of the Bangalore list was blank, because those importers set only
the attributes a dish NAME supports and colour is not one of them.

The fill uses two tiers of evidence and **refuses a third**:

1. **The same dish, coloured in another city.** Four workbooks share most of
   their rows; a dish coloured in Chennai settles the Bangalore copy.
2. **A token vote.** Across the 5,868 coloured rows in all four cities, a word
   that appears in at least 12 dish names and agrees on one colour at least 80%
   of the time is treated as colour-bearing — `palak` is green, `tomato` is
   red, `dosa` is brown, `curd` is white. A candidate's colour is the majority
   of the colour-bearing words in its own name, and only when that majority is
   outright. This is the client's own colour legend rediscovered from the data:
   the legend says "Keerai, peas, sprouts, greens" are green and "Dosa, vada,
   bajji, parotta" golden brown, and the vote independently finds keerai,
   palak, methi, soppu green and dosa, vada, bonda, parotta brown.
3. **NOT the course-type majority.** `veg_gravy` is red in only ~57% of coloured
   rows, so filling by course would put a wrong colour on roughly two of every
   five dishes it touched. A wrong colour is worse than a blank: blank is merely
   invisible to the colour rule, wrong actively tells it the day has a variety
   it does not have. Those rows stay blank and are written to a report the
   client can fill — they clearly can, having supplied a colour for all 583
   dishes in the Chennai bank.

`MODIFIER_STOPWORDS` drops words the vote picks up by accident. `mini`, `mix`,
`broken` and `crispy` describe size or texture and cannot carry a colour; they
reached the threshold only because of what they happen to co-occur with.

Idempotent: a row that already has a colour is never touched.
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CITY_DIR = ROOT / "data" / "raw" / "city_items"
CITIES = ("bangalore", "pune", "chennai", "ncr")
REPORT = ROOT / "docs" / "dishes_needing_a_colour.csv"

#: A token must appear in this many coloured dish names, and agree on one
#: colour this often, before the vote trusts it.
MIN_TOKEN_ROWS = 12
MIN_TOKEN_AGREEMENT = 0.80

#: Words that describe size, texture or preparation rather than an ingredient.
#: They cannot carry a colour, and reached the threshold only through what they
#: happen to sit beside.
MODIFIER_STOPWORDS = {
    "mini", "mix", "mixed", "broken", "crispy", "special", "spl", "plain",
    "regular", "home", "style", "fresh", "hot", "sweet", "spicy", "dry",
    "semi", "full", "half", "small", "large", "baby", "assorted", "veg",
    "vegetable", "non", "combo", "any", "with", "and",
}


def _known(frames) -> pd.DataFrame:
    rows = pd.concat(frames.values(), ignore_index=True)
    return rows[rows["item_color"].notna()]


def colour_by_name(known) -> dict:
    return {str(r["item"]).strip().lower(): str(r["item_color"]).strip().lower()
            for _, r in known.iterrows()}


def colour_bearing_tokens(known) -> dict:
    """{token: colour} for words the coloured rows agree about."""
    tally = defaultdict(Counter)
    for _, r in known.iterrows():
        colour = str(r["item_color"]).strip().lower()
        for t in set(str(r["item"]).strip().lower().split("_")):
            if t and t not in MODIFIER_STOPWORDS:
                tally[t][colour] += 1
    out = {}
    for t, counts in tally.items():
        total = sum(counts.values())
        colour, n = counts.most_common(1)[0]
        if total >= MIN_TOKEN_ROWS and n / total >= MIN_TOKEN_AGREEMENT:
            out[t] = colour
    return out


def infer(item: str, by_name: dict, tokens: dict):
    """(colour, why) for one dish, or (None, why-not)."""
    name = str(item).strip().lower()
    if name in by_name:
        return by_name[name], "same dish coloured in another city"
    votes = Counter(tokens[t] for t in name.split("_") if t in tokens)
    if not votes:
        return None, "no colour-bearing word in the name"
    colour, n = votes.most_common(1)[0]
    if n * 2 <= sum(votes.values()):
        return None, f"its words disagree ({dict(votes)})"
    return colour, f"token vote {dict(votes)}"


def apply(df: pd.DataFrame, by_name: dict, tokens: dict):
    """Return (df, filled, unresolved). Safe to call twice."""
    df = df.copy()
    filled, unresolved = [], []
    for idx in df.index[df["item_color"].isna()]:
        item = str(df.at[idx, "item"]).strip().lower()
        colour, why = infer(item, by_name, tokens)
        if colour:
            df.at[idx, "item_color"] = colour
            filled.append((item, colour, why))
        else:
            unresolved.append((item, str(df.at[idx, "course_type"]).strip(),
                               str(df.at[idx, "client"]), why))
    return df, filled, unresolved


def _atomic_to_excel(frame, path):
    tmp = Path(path).with_name(Path(path).name + ".tmp")
    frame.to_excel(tmp, index=False)
    tmp.replace(path)


def main(dry_run: bool = False):
    frames = {}
    for city in CITIES:
        path = CITY_DIR / f"{city}.xlsx"
        if not path.exists():                              # pragma: no cover
            continue
        d = pd.read_excel(path)
        d.columns = [c.strip() for c in d.columns]
        frames[city] = d

    known = _known(frames)
    by_name = colour_by_name(known)
    tokens = colour_bearing_tokens(known)
    print(f"{len(known)} coloured rows -> {len(tokens)} colour-bearing words")

    all_unresolved = []
    for city, d in frames.items():
        before = int(d["item_color"].isna().sum())
        out, filled, unresolved = apply(d, by_name, tokens)
        print(f"[{city}] blank {before} -> filled {len(filled)}, "
              f"{len(unresolved)} left for the client")
        for item, colour, why in filled[:5]:
            print(f"    {item:<38} {colour:<7} ({why})")
        if len(filled) > 5:
            print(f"    … and {len(filled) - 5} more")
        all_unresolved += [(city, *u) for u in unresolved]
        if filled and not dry_run:
            _atomic_to_excel(out, CITY_DIR / f"{city}.xlsx")
            print(f"[{city}] wrote {city}.xlsx")

    if all_unresolved and not dry_run:
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        with open(REPORT, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["city", "item", "course_type", "client", "why_not"])
            w.writerows(sorted(all_unresolved))
        print(f"\nwrote {REPORT.relative_to(ROOT)} "
              f"({len(all_unresolved)} dishes needing a colour)")
    if dry_run:
        print("\n[dry-run] nothing written")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    main(dry_run=ap.parse_args().dry_run)
