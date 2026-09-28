#!/usr/bin/env python3
"""Give the Marathi-named dishes a `key_ingredient` the rules can select on.

Corning Chakan's menu is the first Maharashtrian list in the ontology, and it
names its vegetables in Marathi: `dodka_masala`, `shepu_moongdal`,
`gawar_masala`, `matki_masala`, `chavali_sheng_dry`, `bharali_wangi`. Nothing in
the ontology had ever carried those words, so `complete_ontology.py` correctly
refused them — a token vote can only propose a value the ontology already uses
for dishes with that word in the name, and there were none.

What it cannot do, a dictionary can. `dodka` IS ridge gourd; that is a fact
about the language, not an inference from the data, and every value below is one
the ontology **already uses** so the existing selectors keep matching:
`ivy_gourd` (13 rows), `cluster_beans`, `black_eyed_pea`, `bitter_gourd`,
`ridge_gourd`, `dill`. Where the ontology's own spelling is the shorter one, that
is what gets written — `moth` rather than `moth_bean`, `yam` rather than
`elephant_yam`, `leafy_greens` rather than `mustard_greens` — because a new
synonym would be invisible to the rules that already name the old one.

`key_ingredient` is not decoration: `attribute_grouping` groups the sambar and
dal slots by it (rulebook 82), `ingredient_ban_rule` matches on it, and
`selector_frequency` can select on it. A blank is invisible to all three, so a
Marathi dish with a blank one silently sits outside every ingredient rule.

Applied to every city, because these words turn up in Bangalore and NCR too
(`gawar`, `tondali`, `suran`). Fills blanks only, so an ontology value already
there always wins. Idempotent.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CITY_DIR = ROOT / "data" / "raw" / "city_items"
sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling scripts
from city_list import CITIES  # noqa: E402

#: Marathi / regional dish word -> the `key_ingredient` value the ontology
#: already uses for that ingredient. Matched as a whole `_`-token.
VEGETABLES = {
    "dodka": "ridge_gourd",          # ridge gourd
    "shepu": "dill",
    "gawar": "cluster_beans",
    "ghewada": "broad_beans",
    "shravani": "broad_beans",       # shravani ghewada, the monsoon bean
    "matki": "moth",                 # moth bean; the ontology writes `moth`
    "chavali": "black_eyed_pea",     # cowpea
    "tondali": "ivy_gourd",
    "tondli": "ivy_gourd",
    "dudhi": "bottle_gourd",
    "bhendi": "okra",
    "bhindi": "okra",
    "karela": "bitter_gourd",
    "suran": "yam",                  # elephant yam; the ontology writes `yam`
    "wangi": "eggplant",             # bharali wangi, stuffed aubergine
    "vangi": "eggplant",
    "baingan": "eggplant",
    "khobra": "coconut",             # ola khobra = fresh coconut
    "shengdana": "peanut",
    "shenga": "peanut",
    "til": "sesame",
    "jawas": "flaxseed",
    "karala": "niger_seed",          # karale, the Maharashtrian oilseed
    "thecha": "chilli",              # a green-chilli relish
    "lasoon": "garlic",
    "birista": "onion",
    "pulihora": "tamarind",
    "sarso": "leafy_greens",         # sarso ka saag, mustard greens
    "methi": "fenugreek",
    "palak": "spinach",
    "gajar": "carrot",
    "kobi": "cabbage",
    "flower": "cauliflower",
    "gobi": "cauliflower",
}

#: Checked BEFORE the single words, because the split lentil and the whole
#: legume are different ingredients with different names: `chana_dal` is split
#: gram, and a bare `chana` is the whole chickpea a chana chaat is made of.
#: Matching one token at a time got `chana_chaat_salad` and `kabuli_chana_chaat`
#: filed as `chana_dal`.
PHRASES = {
    ("chana", "dal"): "chana_dal",
    ("moong", "dal"): "moong_dal",
    ("urad", "dal"): "urad_dal",
    ("toor", "dal"): "toor_dal",
    ("masoor", "dal"): "masoor_dal",
    ("green", "moong"): "green_moong",
    # `chickpea`, not a new `black_chana`: the value has to be one the client's
    # protein list names, or `protein_source_daily` stops seeing the dish. The
    # black-chana distinction is already carried by `is_black_chana_gravy`.
    ("kala", "chana"): "chickpea",
}

#: One ingredient, one spelling. `flaxiseed` is a typo sitting on a single row;
#: leaving it beside the `flaxseed` this script writes would put the same
#: ingredient in the vocabulary twice, which is what makes a `key_ingredient`
#: selector miss half its family.
RENAME = {"flaxiseed": "flaxseed"}

#: The same, for the lentil family. A dal dish is keyed by its lentil.
LENTILS = {
    "amti": "toor_dal",              # the Maharashtrian everyday dal
    "waran": "toor_dal",             # varan; fodanich waran is a tempered varan
    "dalcha": "chana_dal",
    "masoor": "masoor_dal",
    "moongdal": "moong_dal",
    "moong": "moong_dal",
    "patodi": "besan",               # a gram-flour dish
    "toor": "toor_dal",
    "urad": "urad_dal",
    "chana": "chickpea",             # the whole legume, not the split gram
    "chole": "chickpea",
    "rajma": "kidney_bean",
}

#: Courses where the lentil is the key ingredient rather than the vegetable —
#: `shepu_moongdal` is a dill dry veg, `dodka_moongdal` likewise, but a
#: `dal_methi` is a dal keyed by its lentil.
LENTIL_COURSES = {"dal", "sambar", "rasam", "dal_rasam", "dal_sambar"}


def _tokens(name: str):
    return [t for t in str(name).strip().lower().split("_") if t]


def propose(item: str, course: str):
    """(value, why) for one dish, or (None, None)."""
    words = _tokens(item)
    for a, b in zip(words, words[1:]):
        if (a, b) in PHRASES:
            return PHRASES[(a, b)], f"{a}_{b}"
    course = str(course).strip().lower()
    first, second = (LENTILS, VEGETABLES) if course in LENTIL_COURSES \
        else (VEGETABLES, LENTILS)
    for table in (first, second):
        for word in words:
            if word in table:
                return table[word], word
    return None, None


def apply(df: pd.DataFrame):
    """Return (df, filled). Fills blanks only, so it is safe to call twice."""
    df = df.copy()
    if "key_ingredient" not in df.columns:                     # pragma: no cover
        return df, []
    filled = []
    current = df["key_ingredient"].astype(str).str.strip().str.lower()
    for old, new in RENAME.items():
        for idx in df.index[current == old]:
            df.at[idx, "key_ingredient"] = new
            filled.append((str(df.at[idx, "item"]), new, f"was {old}"))
    for idx in df.index[df["key_ingredient"].isna()]:
        value, why = propose(df.at[idx, "item"], df.at[idx, "course_type"])
        if value:
            df.at[idx, "key_ingredient"] = value
            filled.append((str(df.at[idx, "item"]), value, why))
    return df, filled


def _atomic_to_excel(frame, path):
    tmp = Path(path).with_name(Path(path).name + ".tmp")
    frame.to_excel(tmp, index=False)
    tmp.replace(path)


def main(dry_run: bool = False):
    total = 0
    for city in CITIES:
        path = CITY_DIR / f"{city}.xlsx"
        if not path.exists():                                  # pragma: no cover
            continue
        df = pd.read_excel(path)
        df.columns = [c.strip() for c in df.columns]
        before = int(df["key_ingredient"].isna().sum())
        out, filled = apply(df)
        print(f"[{city}] blank key_ingredient {before} -> "
              f"{int(out['key_ingredient'].isna().sum())}"
              f"  ({len(filled)} filled)")
        for item, value, why in filled[:8]:
            print(f"    {item:<30} {why:<12} -> {value}")
        if len(filled) > 8:
            print(f"    … and {len(filled) - 8} more")
        total += len(filled)
        if filled and not dry_run:
            _atomic_to_excel(out, path)
            print(f"[{city}] wrote {city}.xlsx")
    if not total:
        print("nothing to fill — already applied")
    if dry_run:
        print("[dry-run] nothing written")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    main(dry_run=ap.parse_args().dry_run)
