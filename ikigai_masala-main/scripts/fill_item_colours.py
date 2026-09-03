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
3. **An attribute the coloured rows agree about** — `key_ingredient`,
   `course_type` + `key_ingredient`, or a form flag. A different signal from the
   name: `is_leafy_based_dish` is green in 98% of its 353 coloured rows and
   `is_curd_rice` white in all 15, whatever the dish is called. Accepted only at
   >= 85% agreement over >= 8 rows.
4. **NOT the course-type majority.** `veg_gravy` is red in only ~57% of coloured
   rows, so filling by course would put a wrong colour on roughly two of every
   five dishes it touched. A wrong colour is worse than a blank: blank is merely
   invisible to the colour rule, wrong actively tells it the day has a variety
   it does not have.

## What the thresholds are, and why those numbers

The token thresholds were 12 rows / 80% agreement, chosen by judgement. They are
now chosen by **held-out measurement** — train the vote on a random 80% of the
6,445 coloured rows, predict the other 20%, and compare:

| threshold          | coverage | accuracy |
|--------------------|----------|----------|
| 12 rows / 80%      | 21%      | 94%      |
| 8 rows / 75%       | 25%      | 92%      |
| **6 rows / 70%**   | **30%**  | **90%**  |
| 4 rows / 70%       | 32%      | 88%      |
| 3 rows / 65%       | 39%      | 84%      |
| 2 rows / 60%       | 42%      | 79%      |

At 12/80 the vote had run out: it filled **0** of the 2,440 remaining blanks,
because every easy row was already done and what is left has no word the strict
vote trusts. 6/70 is the chosen point — it fills several hundred at a measured
90%, and the accuracy falls away faster than the coverage rises below it.

Filling at 90% is the right trade **for this column**, which is the reverse of
the "wrong is worse than blank" argument above, and worth being explicit about:
a blank colour is not neutral. `MenuSolver._add_color_constraints` clamps the
day's required distinct colours to the number of colours actually PRESENT among
the candidates, so 2,440 invisible dishes quietly relax the rule everywhere —
which is exactly the complaint that started this work. Filling 90% correctly and
10% wrongly leaves the rule working on nine dishes for every one it misjudges.

## What is still missing, and why the data cannot supply it

Even so, most of the gap does not close from inside the repo, and it is worth
saying plainly rather than filling it badly:

* The client's own **colour legend workbook** (`data/raw/source_workbooks/
  client_food_colour_legend.xlsx`, 292 distinct dishes across nine sites) matches
  only **3** of the blank rows. It is a Chennai tiffin list; the blanks are
  Bangalore and NCR north-Indian dishes. Where it *does* overlap rows that are
  already coloured, the two agree **73%** of the time — the client's seven coarse
  badges ("WHITE / LIGHT YELLOW", "BROWN / ORANGE") do not map cleanly onto seven
  discrete colours, so it is a cross-check rather than a source.
* Attribute implication reaches only ~5% of the blanks, because **the rows with
  no colour are largely the rows with no `key_ingredient` either** — the colour
  gap and the attribute gap are the same rows. `nilgiri_veg_korma` and
  `yakhni_pulao` have neither.

So the remainder goes to `docs/dishes_needing_a_colour.csv`, **grouped by dish
family** rather than listed flat: the client can answer ~200 families instead of
~1,700 rows, which is the difference between a request that gets done and one
that does not.

`MODIFIER_STOPWORDS` drops words the vote picks up by accident. `mini`, `mix`,
`broken` and `crispy` describe size or texture and cannot carry a colour; they
reached the threshold only because of what they happen to co-occur with.

Runs to a **fixed point** (a filled colour is evidence for the next pass) and is
idempotent thereafter: a row that already has a colour is never touched.
"""
from __future__ import annotations

import argparse
import sys
import csv
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CITY_DIR = ROOT / "data" / "raw" / "city_items"
sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling scripts
from city_list import CITIES  # noqa: E402
REPORT = ROOT / "docs" / "dishes_needing_a_colour.csv"
GROUPED_REPORT = ROOT / "docs" / "colours_to_confirm_by_family.csv"

#: A token must appear in this many coloured dish names, and agree on one
#: colour this often, before the vote trusts it. Chosen by held-out measurement
#: (see the module docstring): 90% accuracy at 30% coverage, and the accuracy
#: degrades faster than the coverage improves below this point.
MIN_TOKEN_ROWS = 6
MIN_TOKEN_AGREEMENT = 0.70

#: An attribute value must cover this many coloured rows, and agree this often,
#: before it is treated as colour-bearing. Stricter than the token vote because
#: an attribute is a blunter instrument — `course_type` alone would qualify at
#: any looser setting, and it is exactly what must not.
MAX_PASSES = 6

MIN_ATTR_ROWS = 8
MIN_ATTR_AGREEMENT = 0.85

#: Attribute combinations to learn from, most specific first.
ATTR_KEYS = (("course_type", "key_ingredient"), ("key_ingredient",),
             ("course_type", "sub_category"))

#: Words that describe size, texture or preparation rather than an ingredient.
#: They cannot carry a colour, and reached the threshold only through what they
#: happen to sit beside.
MODIFIER_STOPWORDS = {
    "mini", "mix", "mixed", "broken", "crispy", "special", "spl", "plain",
    "regular", "home", "style", "fresh", "hot", "sweet", "spicy", "dry",
    "semi", "full", "half", "small", "large", "baby", "assorted", "veg",
    "vegetable", "non", "combo", "any", "with", "and",
}


#: ``(item, course_type) -> (colour, reason)`` for a dish no tier can decide.
#:
#: Three dishes, all with the same origin: the client's enrichment pass DROPPED
#: them as generic and we deliberately kept them (`mixed_veg` and `sprouts` are
#: dish families rather than slot names — see `remove_generic_rows.py`;
#: `mixed_fruit_crush` is a welcome drink distinct from the `mixed_fruit_custard`
#: dessert, which is `canonical_dish_spellings.KNOWN_SPLITS`). So no enriched
#: colour crosses over for them, and each falls just short of a MEASURED
#: threshold below — which is a reason to give a verdict, not to loosen one:
#:
#:   * `mixed_veg`: `(veg_dry, mixed_vegetables)` is green in 92 of 117 rows —
#:     79%, six points under `MIN_ATTR_AGREEMENT`. Note the same key across ALL
#:     courses is green only 27% of the time, which is exactly why the tier is
#:     scoped by course and why the cross-course figure must not be used.
#:   * `sprouts`: every plain sprouts SALAD is green (`sprouts_salad`,
#:     `green_sprouts`, `sprouts_kosambari`, `mixed_sprouts_salad`) — 8 of 11,
#:     but the token vote needs the agreement, not just the count.
#:   * `mixed_fruit_crush`: the `crush` family is orange in both rows that
#:     carry it (`mixed_crush`, `orange_crush`) — unanimous but only two rows,
#:     under `MIN_TOKEN_ROWS`. Orange follows the name's own family; the mixed
#:     fruit JUICE/punch/smoothie rows are red, and that reading was rejected
#:     because `mixed_crush` is the nearer twin.
#:
#: A blank is not neutral — `MenuSolver._add_color_constraints` clamps a day's
#: required distinct colours to the number PRESENT among the candidates, so an
#: uncoloured row quietly relaxes the rule wherever it is a candidate.
#: `mix_veg` is the same dish under a shorter name, blank in NCR (`veg_dry`) and
#: Pune (`veg_gravy`). It is NOT folded onto `mixed_veg_dry`: Corning Chakan's
#: printed menu splits `mix_veg` out of a "Puri + Mix Veg" cell and
#: `test_corning_pune_import.py` pins it as a Pune `veg_gravy`, so a fold would
#: have to be per-city AND per-course, which is more machinery than a colour.
#: Both courses are listed because each verdict is argued from the row's own
#: course; both are green, and Pune's carries `sub_category: mixed_veg_dry`,
#: which is green in every city that has it.
ADJUDICATED = {
    ("mixed_veg", "veg_dry"): (
        "green", "(veg_dry, mixed_vegetables) is green in 92/117 rows (79%)"),
    ("mix_veg", "veg_dry"): (
        "green", "the same dish as mixed_veg_dry, green in every city"),
    ("mix_veg", "veg_gravy"): (
        "green", "sub_category mixed_veg_dry is green in every city"),
    ("sprouts", "salad"): (
        "green", "every plain sprouts salad in the list is green (8/11)"),
    ("mixed_fruit_crush", "welcome_drink"): (
        "orange", "the crush family is orange (mixed_crush, orange_crush)"),
}


def _norm(value) -> str:
    return str(value).strip().lower()


def adjudicated_colour(item, course):
    """The hand-given verdict for this dish, or ``(None, None)``.

    Keyed by course as well as name: a colour is a property of the dish, but
    these verdicts are each argued from the dish's own COURSE (the mixed-veg
    evidence is 79% within `veg_dry` and 27% across all courses), so applying
    one to a same-named row in another category would be applying an argument
    that was never made.
    """
    hit = ADJUDICATED.get((_norm(item), _norm(course)))
    return hit if hit else (None, None)


def _known(frames) -> pd.DataFrame:
    """The coloured rows, ONE PER DISH.

    Every tier below weighs evidence by how many rows carry it, against
    thresholds picked by held-out measurement (6 rows / 70% agreement = 90%
    accuracy at 30% coverage). The city workbooks overlap heavily, so a dish
    coloured in four cities was already counted four times — and
    `hyderabad.xlsx`, seeded from Bangalore's list, doubled the weight of ~6,000
    Bangalore rows without adding one new fact about them. That alone would have
    coloured 249 dishes across the four established workbooks, all of them rows
    this script had previously looked at and left for the client to confirm. The
    measurement that set the thresholds counted dishes, so the vote must too.

    A colour is a property of the dish, so the key is `item` alone (unlike
    `complete_ontology.distinct_dishes`, which keys on the course as well
    because a dish filed as a `dal` in one city and a `veg_gravy` in another is
    two facts). City order — reference city first, see `city_list` — decides
    which copy survives where two disagree, so the master's colour wins.
    """
    rows = pd.concat(frames.values(), ignore_index=True)
    known = rows[rows["item_color"].notna()]
    return known[~known["item"].astype(str).str.strip().str.lower().duplicated()]


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


def colour_bearing_attributes(known) -> dict:
    """{(columns, values): colour} for attribute values the coloured rows agree
    about — a signal independent of the dish name, which is what the rows with
    no colour-bearing word need."""
    out = {}
    for cols in ATTR_KEYS:
        tally = defaultdict(Counter)
        for _, r in known.iterrows():
            key = tuple(_norm(r.get(c)) for c in cols)
            if any(k in ("", "nan") for k in key):
                continue
            tally[key][_norm(r["item_color"])] += 1
        for key, counts in tally.items():
            total = sum(counts.values())
            colour, n = counts.most_common(1)[0]
            if total >= MIN_ATTR_ROWS and n / total >= MIN_ATTR_AGREEMENT:
                out.setdefault((cols, key), colour)
    return out


def colour_bearing_flags(known) -> dict:
    """{flag: colour} for form flags the coloured rows agree about.

    `is_leafy_based_dish` is green in 98% of its 353 rows and `is_curd_rice`
    white in all 15 — true whatever the dish is called, so this catches dishes
    whose name carries nothing.
    """
    out = {}
    for col in [c for c in known.columns if str(c).startswith("is_")]:
        on = known[pd.to_numeric(known[col], errors="coerce") == 1]
        if len(on) < MIN_ATTR_ROWS:
            continue
        counts = Counter(_norm(v) for v in on["item_color"])
        colour, n = counts.most_common(1)[0]
        if n / len(on) >= MIN_ATTR_AGREEMENT:
            out[col] = colour
    return out


def infer(item: str, by_name: dict, tokens: dict, row=None,
          attrs: dict = None, flags: dict = None):
    """(colour, why) for one dish, or (None, why-not).

    Tiers in order of evidence: the same dish coloured elsewhere, then the token
    vote, then — only when the name says nothing — an attribute or a form flag.
    """
    name = str(item).strip().lower()
    if name in by_name:
        return by_name[name], "same dish coloured in another city"
    votes = Counter(tokens[t] for t in name.split("_") if t in tokens)
    if votes:
        colour, n = votes.most_common(1)[0]
        if n * 2 > sum(votes.values()):
            return colour, f"token vote {dict(votes)}"
        return None, f"its words disagree ({dict(votes)})"
    if row is not None:
        for cols in ATTR_KEYS:
            key = tuple(_norm(row.get(c)) for c in cols)
            hit = (attrs or {}).get((cols, key))
            if hit:
                return hit, f"{'+'.join(cols)}={'/'.join(key)}"
        for flag, colour in (flags or {}).items():
            if pd.to_numeric([row.get(flag)], errors="coerce")[0] == 1:
                return colour, f"flag {flag}"
    return None, "no colour-bearing word, attribute or flag"


def apply(df: pd.DataFrame, by_name: dict, tokens: dict,
          attrs: dict = None, flags: dict = None):
    """Return (df, filled, unresolved). Safe to call twice."""
    df = df.copy()
    filled, unresolved = [], []
    for idx in df.index[df["item_color"].isna()]:
        item = str(df.at[idx, "item"]).strip().lower()
        colour, why = adjudicated_colour(item, df.at[idx, "course_type"])
        if not colour:
            colour, why = infer(item, by_name, tokens, df.loc[idx], attrs, flags)
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


def _question_tokens(item: str) -> set:
    """The words in a dish name that could name a family worth asking about."""
    return {w for w in str(item).strip().lower().split("_")
            if w and w not in MODIFIER_STOPWORDS and len(w) > 2}


def group_questions(unresolved):
    """Fewest (word, course) questions that cover every unresolved dish.

    A greedy set cover, because the point of the report is how many answers the
    client has to give. Grouping each dish by, say, the longest word in its name
    gave 1,057 groups for 1,696 rows — 804 of them singletons — which is not a
    smaller question, just a differently shaped one. Picking the word that
    covers the most still-uncovered dishes, repeatedly, gives 448: the top 25
    answers colour half the backlog and the top 100 cover three quarters.

    Returns ``[((word, course), [members])]``, largest first, plus the dishes no
    shared word reaches (they need answering one at a time).
    """
    items = [(city, item, course) for city, item, course, _cl, _why in unresolved]
    by_token = defaultdict(set)
    for i, (_city, item, course) in enumerate(items):
        for tok in _question_tokens(item):
            by_token[(tok, _norm(course))].add(i)

    uncovered = set(range(len(items)))
    groups = []
    while uncovered:
        best, covered = None, set()
        # `sorted` is load-bearing: `_question_tokens` returns a SET, and set
        # iteration order is hash-salted per process, so an unsorted scan broke
        # ties differently on every run and the committed report changed by a
        # group or two each time. A derived artefact that will not reproduce
        # cannot be tested.
        for key in sorted(by_token):
            hit = by_token[key] & uncovered
            if len(hit) > len(covered):
                best, covered = key, hit
        if not best or not covered:
            break                        # only nameless dishes left
        groups.append((best, sorted(covered)))
        uncovered -= covered
    groups.sort(key=lambda g: (-len(g[1]), g[0]))
    leftovers = [items[i] for i in sorted(uncovered)]
    return groups, items, leftovers


def _write_grouped_report(unresolved) -> int:
    """One row per question, so the client answers ~450 families rather than
    ~1,700 dishes. Ordered by how many dishes each answer colours, so stopping
    early still helps."""
    groups, items, leftovers = group_questions(unresolved)
    with open(GROUPED_REPORT, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["dish_family", "course_type", "n_dishes", "item_color",
                    "example_dishes"])
        for (token, course), members in groups:
            names = [f"{items[i][0]}:{items[i][1]}" for i in members]
            w.writerow([token, course, len(members), "",
                        "; ".join(sorted(names)[:6])])
        for city, item, course in leftovers:
            w.writerow([item, _norm(course), 1, "", f"{city}:{item}"])
    return len(groups) + len(leftovers)


def main(dry_run: bool = False):
    frames = {}
    for city in CITIES:
        path = CITY_DIR / f"{city}.xlsx"
        if not path.exists():                              # pragma: no cover
            continue
        d = pd.read_excel(path)
        d.columns = [c.strip() for c in d.columns]
        frames[city] = d

    # Runs to a FIXED POINT, because every colour filled is evidence for the
    # next pass: a newly coloured `palak_paneer` teaches the vote about `palak`.
    # Without the loop one invocation left 77 rows that a second would have
    # filled, so the correction chain did not converge and the README's promise
    # that a re-run reports "already correct" was false for this script.
    before_total = {c: int(d["item_color"].isna().sum()) for c, d in frames.items()}
    filled_total = {c: [] for c in frames}
    unresolved_by_city = {c: [] for c in frames}
    for sweep in range(1, MAX_PASSES + 1):
        known = _known(frames)
        by_name = colour_by_name(known)
        tokens = colour_bearing_tokens(known)
        attrs = colour_bearing_attributes(known)
        flags = colour_bearing_flags(known)
        moved = 0
        for city, d in frames.items():
            out, filled, unresolved = apply(d, by_name, tokens, attrs, flags)
            frames[city] = out
            filled_total[city] += filled
            unresolved_by_city[city] = unresolved
            moved += len(filled)
        print(f"pass {sweep}: {len(known)} coloured rows -> {len(tokens)} words, "
              f"{len(attrs)} attribute rules, {len(flags)} flag rules; "
              f"{moved} filled")
        if not moved:
            break

    all_unresolved = []
    for city, d in frames.items():
        filled = filled_total[city]
        print(f"[{city}] blank {before_total[city]} -> filled {len(filled)}, "
              f"{len(unresolved_by_city[city])} left for the client")
        for item, colour, why in filled[:5]:
            print(f"    {item:<38} {colour:<7} ({why})")
        if len(filled) > 5:
            print(f"    … and {len(filled) - 5} more")
        all_unresolved += [(city, *u) for u in unresolved_by_city[city]]
        if filled and not dry_run:
            _atomic_to_excel(d, CITY_DIR / f"{city}.xlsx")
            print(f"[{city}] wrote {city}.xlsx")

    if all_unresolved and not dry_run:
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        with open(REPORT, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["city", "item", "course_type", "client", "why_not"])
            w.writerows(sorted(all_unresolved))
        print(f"\nwrote {REPORT.relative_to(ROOT)} "
              f"({len(all_unresolved)} dishes needing a colour)")
        n_groups = _write_grouped_report(all_unresolved)
        print(f"wrote {GROUPED_REPORT.relative_to(ROOT)} "
              f"({n_groups} families — answer these, not the {len(all_unresolved)} rows)")
    if dry_run:
        print("\n[dry-run] nothing written")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    main(dry_run=ap.parse_args().dry_run)
