#!/usr/bin/env python3
"""Complete the city ontologies: flags, sub_category, key_ingredient, regions.

Six client menu imports added ~2,400 dishes, each carrying only the attributes
its NAME supported — course_type, cuisine_family, protein — because inventing a
sub_category for a dish nobody has classified is inventing data the rules then
act on. That was the right call at import time and the wrong place to leave it:
**1,773 rows across the four cities have every `is_*` flag at zero**, and a dish
with no flags is invisible to every flag-driven rule. It sits in the pool,
passes every diagnostic, and is never the dish a rule asks for.

Nothing here is guessed. Each channel is measured against the rows the ontology
already classifies, and only channels that reproduce those labels are used:

1. **Course mirrors.** Nine flags simply restate the row's course — every
   classified `dessert` carries `is_dessert` (512/526), every classified
   `veg_dry` carries `is_veg_dry` (941/945). The handful that don't are holes,
   not counter-examples: the classified desserts missing the flag are `kulfi`,
   `rava_kesari`, `millet_payasam`. So the flag is set for every row of that
   course. `COURSE_MIRRORS` records the measured coverage; a test re-derives it.

2. **Attribute implication.** A `(course, column, value)` that predicts a flag
   in at least `MIN_SUPPORT` classified rows and at least `MIN_PRECISION` of
   them implies it — `sub_category == raita` ⇒ `is_raita`, `chicken_north_masala`
   ⇒ `is_nonveg_gravy`. This reaches 89 of the 112 flags and is learned from the
   data rather than written out by hand.

3. **Token vote**, for the columns and the ~13 flags no attribute reaches
   (`is_buttermilk`, `is_lemon_drink`, `is_deep_fried_veg_dry`, …): a word that
   appears in `MIN_ROWS` classified dishes of the same course and agrees
   `MIN_AGREEMENT` of the time is trusted. This is what `fill_item_colours.py`
   does for colour, generalised. It can only ever propose a value the ontology
   already uses for dishes with that word in the name; a word nobody agrees
   about proposes nothing and the row stays blank and is reported.

**Premium is reported, not written.** The client stated the rule — *"premium is
a dish like paneer, baby corn, mushroom, a lot of vegetable will increase the
cost of the items, and rich continental stuff"* — and `is_premium` encodes it
faithfully. But the three premium flags are the inputs to shipped COST rules
that serve exactly one premium gravy and one premium veg dry a *week*, and
applying the client's definition takes `is_premium_gravy` from 174 rows to 463,
at which point that rule stops meaning "the week's showcase dish" and starts
meaning "paneer at most once a week". That is a menu-policy decision rather
than a data gap, so it goes back to the client: `--report-premium` prints what
their definition would mark, and `APPLY_PREMIUM` is the switch once they have
chosen. See the comment on that constant, and `--report-mixed-veg` for the one
clause that is over-broad on its own terms.

`richness_score` is untouched: 6,092 of 6,169 Bangalore rows are 0 and nothing
reads it, so filling it would be inventing a number with no meaning. Flags that
another correction script owns for a course are left to it, so two scripts never
fight over one cell — `nonveg_structural_flags.py` decides a non-veg dish's form
and `seafood_taxonomy.py` decides seafood.

Idempotent, and monotone: a cell that already holds a value is never
overwritten and a flag is only ever set 0 -> 1. Whatever the evidence cannot
settle goes to `docs/ontology_gaps.csv`.
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
REPORT = ROOT / "docs" / "ontology_gaps.csv"

#: A token must appear in this many classified rows of the same course, and
#: agree this often, before it is trusted.
MIN_ROWS = 8
MIN_AGREEMENT = 0.85

#: An attribute value must predict a flag in this many classified rows, this
#: reliably, before it implies it.
MIN_SUPPORT = 5
MIN_PRECISION = 0.95

#: Text columns worth completing, and the courses each one applies to. A blank
#: `dal_region` on a dessert is not a gap — the column does not apply — so the
#: report counts a blank only inside its own scope. `sub_category` and
#: `key_ingredient` apply everywhere and are absent from this map.
COLUMN_SCOPE = {
    "sub_category": None,
    "key_ingredient": None,
    "dal_region": {"dal"},
    "dessert_form": {"dessert"},
    "drink_type": {"welcome_drink"},
    "drink_rule_group": {"welcome_drink"},
    "nonveg_biryani_region": {"nonveg_main"},
    "flavoured_rice_region": {"rice", "healthy_rice"},
    "gravy_region": {"veg_gravy", "nonveg_main"},
}

#: Flags that restate the row's course, with the coverage measured among the
#: rows the ontology already classifies. `test_complete_ontology.py` re-derives
#: these from the workbooks and fails if one stops holding.
#:
#: A mirror is definitional in BOTH directions, so an off-course row carrying
#: one is cleared. Every such row today is residue from a dish being re-filed:
#: `course_type_corrections.py` moved `moong_dal_dosa` from `dal` to `bread` and
#: `ncr_bread_misfiles.py` moved `jodhpuri_pulao` out of `bread`, but neither
#: cleared the flag the old course had put there — so a dal rule could still
#: pick the dosa. Twelve rows across the four cities.
COURSE_MIRRORS = {
    "is_bread": ({"bread"}, 0.997),
    "is_dal": ({"dal"}, 0.998),
    "is_salad": ({"salad"}, 0.998),
    "is_veg_dry": ({"veg_dry"}, 0.996),
    "is_rice": ({"rice", "healthy_rice"}, 1.000),
    "is_sambar": ({"sambar"}, 0.978),
    "is_dessert": ({"dessert"}, 0.973),
    "is_soup": ({"soup"}, 0.960),
    "is_veg_starter": ({"starter"}, 0.945),
    "is_welcome_drink": ({"welcome_drink"}, 0.939),
}

#: Flags that restate a NON-course column, measured the same way.
#: `is_egg_dish` is every egg dish and nothing else: 166/166 recall, and its one
#: exception (`egg_curry_masala` carries the protein without the flag) is a hole
#: this fills. `is_continental` is deliberately NOT here — it agrees with
#: `cuisine_family == continental` only 87% of the time in one direction and 84%
#: in the other, so the flag is genuinely noisier than the column.
COLUMN_MIRRORS = {
    "is_egg_dish": ("primary_protein", "egg", 1.000),
}

#: Words that carry no meaning of their own — function words, and modifiers of
#: size, style or spice that describe a dish without identifying it. A token
#: vote picks them up purely from what they sit beside: `of` proposed
#: `is_dairy_based` because of `cream_of_spinach`, and `masala` proposed
#: `is_deep_fried_starter` because of `masala_puri`. Same failure, and same
#: remedy, as `MODIFIER_STOPWORDS` in `fill_item_colours.py`.
TOKEN_STOPWORDS = {
    "of", "and", "with", "in", "the", "a", "an", "or", "on", "ka", "ke", "ki",
    "masala", "style", "special", "spl", "plain", "regular", "home", "fresh",
    "hot", "mixed", "mix", "assorted", "veg", "vegetable", "vegetables", "non",
    "combo", "any", "semi", "full", "half", "small", "large", "mini", "baby",
    "dry", "curry", "sabzi", "subzi", "gravy", "sauce", "recipe", "served",
}

#: Two flags that NEVER co-occur in a course, each on this many rows, are taken
#: to be mutually exclusive — `is_dosa` and `is_paratha` (50 and 105 rows, zero
#: overlap), `is_nonveg_dry` and `is_nonveg_gravy`, `is_plain_curd` and
#: `is_raita`. Derived rather than hand-listed, because guessing gets the
#: hierarchy wrong: `is_stuffed_paratha` looks like a peer of `is_paratha` and
#: is really a subset of it, and `is_dosa` ⊂ `is_dosa_family`.
#:
#: This matters because the two inference channels are existential — every
#: matching word and attribute fires — so `paneer_masala_dosa` drew `is_dosa`
#: from the word `dosa` and `is_paratha` from `key_ingredient == paneer`, every
#: classified paneer bread in the ontology being a paneer paratha. When two
#: proposals conflict the better-evidenced one wins: the dish's own NAME beats
#: an attribute, and a later word beats an earlier one, Indian dish names
#: putting the form last.
MIN_EXCLUSIVE_SUPPORT = 10

#: How many learn-and-apply passes before giving up on convergence. Three is
#: generous: the first pass does ~99% of the work and the second ~1%.
MAX_PASSES = 6

#: Flags no single ingredient word can settle — see `COLUMN_MIRRORS`.
NOT_TOKEN_INFERRED = {"is_continental"}

#: Categorical columns an implication may be learned from. `cuisine_family` is
#: deliberately absent: inside one course it is nearly a tautology, and the one
#: rule it produced — `(rice, north_indian) => is_rice` — carried no information
#: the course did not already carry while faithfully propagating a course
#: misfile into a flag. `is_rice` is a mirror above instead, on stronger
#: evidence: every classified `rice` and `healthy_rice` row carries it.
ATTRIBUTE_COLUMNS = ("sub_category", "key_ingredient",
                     "primary_protein", "dal_region", "gravy_region",
                     "dessert_form", "drink_type", "flavoured_rice_region")

#: (flag, course) pairs another correction script is authoritative for. Scoped
#: by course rather than by column: `nonveg_structural_flags.py` decides the
#: FORM of a non-veg dish (dry / gravy / biryani, mutually exclusive, chosen by
#: priority), so this must not also vote there — but `is_biryani_item` on a veg
#: biryani in `rice` is nobody else's, and is filled normally.
OWNED_ELSEWHERE = {
    ("is_nonveg_dry", "nonveg_main"), ("is_nonveg_gravy", "nonveg_main"),
    ("is_nonveg_biryani", "nonveg_main"), ("is_biryani_item", "nonveg_main"),
    ("is_north_chicken_gravy", "nonveg_main"),
    ("is_south_chicken_gravy", "nonveg_main"),
    ("is_seafood", "nonveg_main"), ("is_fish_dish", "nonveg_main"),
}

#: Derived at the end from what the row actually holds, never learned.
DERIVED_FLAGS = {"is_rule_ready"}

#: The ingredients the client named, plus the kin the ontology already treats
#: the same way (of 383 premium rows, 217 are its paneer_curry / soya_curry
#: sub_categories) and the rich dairy and nuts that carry the same cost.
PREMIUM_INGREDIENTS = {
    "paneer", "cottage_cheese", "mushroom", "baby_corn", "babycorn", "soya",
    "soyabean", "tofu", "cashew", "kaju", "badam", "almond", "pista",
    "dry_fruit", "dryfruit", "khoya", "malai", "cream", "cheese",
}

#: "a lot of vegetable" as a rich PREPARATION rather than as the catch-all
#: key_ingredient. `navratan` ("nine gems") is in the ontology's own premium
#: rows; the blanket reading is reported instead (see the module docstring).
PREMIUM_MIXED = {"navratan"}

#: The catch-all this deliberately does NOT treat as premium.
MIXED_VEG_CATCHALL = "mixed_vegetables"

#: "rich continental stuff" — continental AND a word that makes it rich. Plain
#: continental is not enough: bruschetta, falafel and hummus are continental and
#: are not premium.
RICH_WORDS = {"malai", "cream", "creamy", "cheese", "alfredo", "gratin",
              "bechamel", "mornay"}

#: **The premium flags are reported, never written.** They are not descriptive
#: attributes — they are the inputs to three shipped COST rules, and those rules
#: are calibrated to how many dishes carry them:
#:
#:     premium_veg_gravy_exactly_one   is_premium_gravy   @veg_gravy  exact: 1
#:     premium_veg_dry_exactly_one     is_premium_veg_dry @veg_dry    exact: 1
#:     premium_veg_daily_max_1         is_premium_veg     daily_max: 1
#:
#: `exact: 1` counts DAYS, so it means "one premium veg gravy a *week*" — the
#: week's one showcase dish. Chennai's ruleset even records the count it was
#: written against ("One premium veg gravy a week (25 eligible rows)").
#:
#: The client's definition — paneer, baby corn, mushroom, rich continental — is
#: a statement about COST, and applied literally it marks 1,247 Bangalore rows
#: premium and takes `is_premium_gravy` from 174 to 463. Both readings are
#: defensible and they are not compatible: at 463 the weekly rule stops meaning
#: "the showcase dish" and starts meaning "paneer at most once a week", which
#: fights `paneer_prefers_mix_south_north` and would leave a themed day whose
#: gravies are ALL premium forcing the cap past `exact: 1` — the reportable
#: conflict of note 9e.
#:
#: That is a menu-policy decision, not a data gap, so it goes back to the
#: client: `--report-premium` prints what their definition would mark, per city
#: and per flag. Flipping `APPLY_PREMIUM` to True is the whole change once they
#: have chosen, and the weekly caps would need re-deriving with it.
APPLY_PREMIUM = False

#: Which premium flag applies to which course.
PREMIUM_FLAG_BY_COURSE = {
    "veg_gravy": ("is_premium_veg", "is_premium_gravy"),
    "veg_dry": ("is_premium_veg", "is_premium_veg_dry"),
    "starter": ("is_premium_veg",),
    "rice": ("is_premium_veg",),
}

#: A row is rule-ready when it carries everything the rules actually read.
RULE_READY_COLUMNS = ("course_type", "cuisine_family", "item_color",
                      "sub_category", "key_ingredient")


def _norm(v) -> str:
    s = str(v).strip().lower()
    return "" if s in ("", "nan", "none") else s


def _tokens(name: str):
    return [t for t in str(name).strip().lower().split("_") if t]


def flag_columns(d) -> list:
    return [c for c in d.columns if c.startswith("is_")]


def _numeric_flags(d) -> pd.DataFrame:
    return d[flag_columns(d)].apply(pd.to_numeric, errors="coerce").fillna(0)


def flagless(d) -> pd.Series:
    """Rows carrying no flag at all — where a 0 means 'unknown', not 'false'."""
    return _numeric_flags(d).sum(axis=1) == 0


def _classified(everything: pd.DataFrame) -> pd.DataFrame:
    return everything[_numeric_flags(everything).sum(axis=1) > 0]


def learn_text(classified, column: str) -> dict:
    """{(course, token): value} the classified rows agree about."""
    tally = defaultdict(Counter)
    for _, r in classified.iterrows():
        value = _norm(r.get(column))
        if not value:
            continue
        course = _norm(r.get("course_type"))
        for t in set(_tokens(r["item"])):
            tally[(course, t)][value] += 1
    out = {}
    for key, counts in tally.items():
        total = sum(counts.values())
        value, n = counts.most_common(1)[0]
        if total >= MIN_ROWS and n / total >= MIN_AGREEMENT:
            out[key] = value
    return out


def learn_flag_tokens(classified, flags) -> dict:
    """{(course, token): {flag, …}} — words that PREDICT a flag being set.

    Positive-predictive on purpose. A plain majority vote over 0 and 1 is
    useless here: most words sit in rows where most flags are 0, so the 0s
    always win and no flag is ever proposed.
    """
    seen = defaultdict(int)
    hits = defaultdict(Counter)
    numeric = _numeric_flags(classified)
    votable = [f for f in flags if f not in NOT_TOKEN_INFERRED]
    for pos, (_, r) in enumerate(classified.iterrows()):
        course = _norm(r.get("course_type"))
        row = numeric.iloc[pos]
        on = [f for f in votable if row.get(f, 0) == 1]
        for t in set(_tokens(r["item"])) - TOKEN_STOPWORDS:
            seen[(course, t)] += 1
            for f in on:
                hits[(course, t)][f] += 1
    out = defaultdict(set)
    for key, total in seen.items():
        if total < MIN_ROWS:
            continue
        for f, n in hits[key].items():
            if n / total >= MIN_AGREEMENT:
                out[key].add(f)
    return dict(out)


def learn_exclusive_pairs(classified, flags) -> set:
    """{(course, a, b)} for flags that never co-occur on enough evidence."""
    numeric = _numeric_flags(classified)
    course = classified["course_type"].astype(str).str.strip().str.lower()
    out = set()
    for name in course.unique():
        sub = numeric[(course == name).values]
        present = [f for f in flags
                   if f in sub.columns and (sub[f] == 1).sum() >= MIN_EXCLUSIVE_SUPPORT]
        for i, a in enumerate(present):
            on_a = sub[a] == 1
            for b in present[i + 1:]:
                if not (on_a & (sub[b] == 1)).any():
                    # sorted, because the lookup sorts — storing them in column
                    # order made every pair a silent miss
                    out.add((name, *sorted((a, b))))
    return out


def _resolve_conflicts(proposals: dict, already_on: set, course: str,
                       exclusive: set) -> list:
    """Keep the best-evidenced flag from each conflicting pair.

    `proposals` maps a flag to its evidence rank (higher is better): an
    attribute implication scores 0, a word in the dish's own name scores by its
    position, so the last word wins. Flags the row already carries are kept
    outright — they are the ontology's own classification, not a proposal.
    """
    kept = list(already_on)
    for flag in sorted(proposals, key=lambda f: (-proposals[f], f)):
        if any((course, *sorted((flag, k))) in exclusive for k in kept):
            continue
        kept.append(flag)
    return [f for f in kept if f in proposals]


def learn_attribute_rules(classified, flags) -> dict:
    """{(course, column, value): {flag, …}} implied at MIN_PRECISION."""
    numeric = _numeric_flags(classified)
    out = defaultdict(set)
    course = classified["course_type"].astype(str).str.strip().str.lower()
    for column in ATTRIBUTE_COLUMNS:
        if column not in classified.columns:
            continue
        value = classified[column].astype(str).str.strip().str.lower()
        usable = value.isin(("", "nan", "none")) == False       # noqa: E712
        key = list(zip(course[usable], value[usable]))
        if not key:
            continue
        sub = numeric[usable.values]
        grouped = sub.groupby(pd.MultiIndex.from_tuples(key))
        size = grouped.size()
        total = grouped.sum()
        for f in flags:
            if f not in total.columns:
                continue
            ok = (size >= MIN_SUPPORT) & (total[f] > 0) & \
                 (total[f] / size >= MIN_PRECISION)
            for c, v in total.index[ok]:
                out[(c, column, v)].add(f)
    return dict(out)


def _names(item: str, phrases) -> bool:
    """Does the dish name contain one of these, as whole `_`-delimited words?

    Matched as a phrase rather than a token, because the client named ingredients
    that are two words: `baby_corn` is never a token of
    `baby_corn_manchurian_gravy`, so a token test silently missed every baby-corn
    dish — exactly the ingredient the client called out by name.
    """
    padded = f"_{_norm(item)}_"
    return any(f"_{p}_" in padded for p in phrases)


def is_premium(row) -> bool:
    """The client's rule: paneer / baby corn / mushroom / rich continental."""
    key = _norm(row.get("key_ingredient"))
    if key in PREMIUM_INGREDIENTS or _names(row["item"], PREMIUM_INGREDIENTS):
        return True
    if _names(row["item"], PREMIUM_MIXED):
        return True
    return (_norm(row.get("cuisine_family")) == "continental"
            and _names(row["item"], RICH_WORDS))


def _applies(column: str, course: str) -> bool:
    scope = COLUMN_SCOPE.get(column)
    return scope is None or course in scope


def apply(d: pd.DataFrame, learned_text: dict, attribute_rules: dict,
          flag_tokens: dict, exclusive: set = frozenset()):
    """Return (df, filled, unresolved). Safe to call twice."""
    d = d.copy()
    filled, unresolved = [], []
    flags = flag_columns(d)
    #: Which rows carry no flag at all, measured BEFORE anything is written —
    #: the course-mirror pass below sets flags, and taking the mask afterwards
    #: would exclude exactly the rows the later channels exist to fill.
    bare = flagless(d)

    def already_set(idx, column) -> bool:
        return pd.to_numeric(pd.Series([d.at[idx, column]]),
                             errors="coerce").fillna(0).iloc[0] == 1

    def turn_on(idx, column, why):
        if column in DERIVED_FLAGS or column not in d.columns:
            return False
        course = _norm(d.at[idx, "course_type"])
        if (column, course) in OWNED_ELSEWHERE or already_set(idx, column):
            return False
        d.at[idx, column] = 1
        filled.append((str(d.at[idx, "item"]), column, why))
        return True

    # 1. text columns — a blank inside the column's own scope
    for column, learned in learned_text.items():
        if column not in d.columns:
            continue
        for idx in d.index[d[column].isna()]:
            course = _norm(d.at[idx, "course_type"])
            if not _applies(column, course):
                continue
            votes = Counter(learned[(course, t)]
                            for t in _tokens(d.at[idx, "item"])
                            if (course, t) in learned)
            value, n = votes.most_common(1)[0] if votes else (None, 0)
            if value and n * 2 > sum(votes.values()):
                d.at[idx, column] = value
                filled.append((str(d.at[idx, "item"]), column, value))
            else:
                unresolved.append((str(d.at[idx, "item"]), course, column,
                                   "no word its siblings agree about"))

    # 2. course mirrors — definitional, so every row of the course carries the
    #    flag and no other row does
    course_of = d["course_type"].astype(str).str.strip().str.lower()
    for flag, (courses, _) in COURSE_MIRRORS.items():
        if flag not in d.columns:
            continue
        belongs = course_of.isin(courses)
        for idx in d.index[belongs]:
            turn_on(idx, flag, "course mirror")
        for idx in d.index[~belongs]:
            if already_set(idx, flag):
                d.at[idx, flag] = 0
                filled.append((str(d.at[idx, "item"]), flag,
                               f"cleared — course is {course_of[idx]}"))

    # 2b. column mirrors — the same argument, on a column that is not the course
    for flag, (column, value, _) in COLUMN_MIRRORS.items():
        if flag not in d.columns or column not in d.columns:
            continue
        holds = d[column].astype(str).str.strip().str.lower() == value
        for idx in d.index[holds]:
            turn_on(idx, flag, f"{column} mirror")

    # 3 + 4. attribute implication, then a token vote for what it cannot reach.
    #        Only on rows carrying no flag at all: elsewhere a 0 is a decision.
    for idx in d.index[bare]:
        row = d.loc[idx]
        course = _norm(row["course_type"])
        before = len(filled)
        proposals, why = {}, {}
        for column in ATTRIBUTE_COLUMNS:
            if column not in d.columns:
                continue
            value = _norm(row.get(column))
            for flag in attribute_rules.get((course, column, value), ()):
                proposals.setdefault(flag, 0)
                why.setdefault(flag, f"{column}={value}")
        for position, t in enumerate(_tokens(row["item"])):
            if t in TOKEN_STOPWORDS:
                continue
            for flag in flag_tokens.get((course, t), ()):
                if proposals.get(flag, -1) < position + 1:
                    proposals[flag] = position + 1
                    why[flag] = f"token {t}"
        already_on = {f for f in flags if already_set(idx, f)}
        for flag in _resolve_conflicts(proposals, already_on, course, exclusive):
            turn_on(idx, flag, why[flag])
        if len(filled) == before:
            unresolved.append((str(row["item"]), course, "is_* flags",
                               "no attribute or word its siblings agree about"))

    # 5. premium — reported rather than written; see APPLY_PREMIUM
    if APPLY_PREMIUM:                                          # pragma: no cover
        for idx in d.index:
            course = _norm(d.at[idx, "course_type"])
            if course in PREMIUM_FLAG_BY_COURSE and is_premium(d.loc[idx]):
                for column in PREMIUM_FLAG_BY_COURSE[course]:
                    turn_on(idx, column, "client's premium rule")

    # 6. is_rule_ready — what the row actually holds, never lowered
    if "is_rule_ready" in d.columns:
        ready = pd.Series(True, index=d.index)
        for column in RULE_READY_COLUMNS:
            if column in d.columns:
                ready &= d[column].notna()
        ready &= ~flagless(d)
        current = _numeric_flags(d)["is_rule_ready"]
        for idx in d.index[ready & (current != 1)]:
            d.at[idx, "is_rule_ready"] = 1
            filled.append((str(d.at[idx, "item"]), "is_rule_ready", "complete"))
    return d, filled, unresolved


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


def learn_all(frames):
    everything = pd.concat(frames.values(), ignore_index=True)
    classified = _classified(everything)
    flags = [c for c in everything.columns
             if c.startswith("is_") and c not in DERIVED_FLAGS]
    learned_text = {c: learn_text(classified, c) for c in COLUMN_SCOPE}
    return (learned_text,
            learn_attribute_rules(classified, flags),
            learn_flag_tokens(classified, flags),
            learn_exclusive_pairs(classified, flags),
            len(classified))


def report_mixed_veg(frames):
    """How big the blanket 'a lot of vegetable' reading would be."""
    everything = pd.concat(frames.values(), ignore_index=True)
    key = everything.get("key_ingredient", pd.Series(dtype=str))
    hit = key.astype(str).str.strip().str.lower() == MIXED_VEG_CATCHALL
    scoped = hit & everything["course_type"].isin(PREMIUM_FLAG_BY_COURSE)
    already = _numeric_flags(everything)["is_premium_veg"] == 1
    print(f"\nkey_ingredient == {MIXED_VEG_CATCHALL!r}: {int(scoped.sum())} rows "
          f"in the premium courses, of which {int((scoped & ~already).sum())} "
          f"are currently NOT premium.")
    print("Treating the catch-all as premium is the client's 'a lot of "
          "vegetable' clause read at its widest; it is NOT applied. "
          "mixed_veg_curry is the largest sub_category there is, so it would "
          "leave premium_veg_gravy_exactly_one choosing from nearly the whole "
          "pool. Sample:")
    for name in everything[scoped & ~already]["item"].head(12):
        print(f"    {name}")


def report_premium(frames):
    """What the client's definition would mark, against what the rules expect."""
    print("The client's rule — paneer / baby corn / mushroom / rich continental "
          "— against\nwhat each flag carries today. These are NOT applied: see "
          "APPLY_PREMIUM.\n")
    print(f"{'city':<11}{'flag':<20}{'today':>7}{'client rule':>13}")
    for city, d in frames.items():
        course = d["course_type"].astype(str).str.strip().str.lower()
        premium = d.apply(is_premium, axis=1)
        numeric = _numeric_flags(d)
        for flag in ("is_premium_veg", "is_premium_gravy", "is_premium_veg_dry"):
            if flag not in numeric.columns:
                continue
            scope = course.map(
                lambda c: flag in PREMIUM_FLAG_BY_COURSE.get(c, ()))
            would = int(((numeric[flag] == 1) | (premium & scope)).sum())
            print(f"{city:<11}{flag:<20}{int((numeric[flag] == 1).sum()):>7}"
                  f"{would:>13}")
    print("\n`premium_veg_gravy_exactly_one` and `premium_veg_dry_exactly_one` "
          "serve ONE\npremium dish a week each. At the client-rule counts that "
          "reads as 'paneer at\nmost once a week', which is a menu-policy "
          "change rather than a data fix — so\nit needs the client's word "
          "before it is applied, and the weekly caps would\nneed re-deriving "
          "with it.")


def main(dry_run: bool = False, mixed_veg: bool = False,
         premium: bool = False):
    frames = load()
    if mixed_veg:
        report_mixed_veg(frames)
        return
    if premium:
        report_premium(frames)
        return
    bare_before = {c: int(flagless(d).sum()) for c, d in frames.items()}
    total = defaultdict(list)
    all_unresolved = []

    # Run to a fixed point. Each pass classifies more rows, so the NEXT pass
    # learns from a larger set and can reach further — which also means a second
    # invocation of the script would otherwise keep finding work, and the whole
    # correction-script convention here is that re-running changes nothing.
    # Converging inside one run is what makes the second run a real no-op.
    for pass_no in range(1, MAX_PASSES + 1):
        learned_text, attribute_rules, flag_tokens, exclusive, n_classified = \
            learn_all(frames)
        print(f"pass {pass_no}: learned from {n_classified} classified rows — "
              f"{sum(len(v) for v in learned_text.values())} text rules, "
              f"{sum(len(v) for v in attribute_rules.values())} attribute "
              f"implications, {sum(len(v) for v in flag_tokens.values())} token "
              f"implications, {len(exclusive)} exclusive pairs")
        moved = 0
        all_unresolved = []
        for city, d in frames.items():
            out, filled, unresolved = apply(d, learned_text, attribute_rules,
                                            flag_tokens, exclusive)
            frames[city] = out
            total[city] += filled
            moved += len(filled)
            all_unresolved += [(city, *u) for u in unresolved]
        print(f"         {moved} values filled")
        if not moved:
            break
    else:                                                      # pragma: no cover
        print(f"WARNING: still filling after {MAX_PASSES} passes — not converged")

    for city, d in frames.items():
        filled = total[city]
        print(f"[{city}] {len(filled)} values filled; "
              f"flagless rows {bare_before[city]} -> {int(flagless(d).sum())}")
        for col, n in Counter(c for _, c, _ in filled).most_common(8):
            print(f"    {col:<28} {n}")
        if filled and not dry_run:
            _atomic_to_excel(d, CITY_DIR / f"{city}.xlsx")
            print(f"[{city}] wrote {city}.xlsx")

    gaps = sorted(set(all_unresolved))
    if gaps and not dry_run:
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        with open(REPORT, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["city", "item", "course_type", "column", "why_not"])
            w.writerows(gaps)
        print(f"\nwrote {REPORT.relative_to(ROOT)} ({len(gaps)} gaps left)")
    if dry_run:
        print(f"\n[dry-run] nothing written; {len(gaps)} gaps would be reported")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report-mixed-veg", action="store_true",
                    help="size the clause this deliberately does not apply")
    ap.add_argument("--report-premium", action="store_true",
                    help="what the client's premium rule would mark, and why "
                         "it is not applied")
    args = ap.parse_args()
    main(dry_run=args.dry_run, mixed_veg=args.report_mixed_veg,
         premium=args.report_premium)
