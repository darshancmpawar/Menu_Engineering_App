#!/usr/bin/env python3
"""Dish names carrying a MISSPELLED protein word — and the veg rows hiding behind them.

Four rows across two cities are named for chicken or mutton while every
attribute says vegetarian, so the solver serves them from the **veg** pools and
the menu prints a meat name to a vegetarian:

    bangalore  chciken_kebab            starter    is_veg_starter=1, protein='',
                                                   key_ingredient=besan
    bangalore  hoskote_chciken_biryani  rice       is_mixedveg_biryani=1, protein='',
                                                   sub_category=north_veg_biryani
    ncr        hyderabadi_chivken       veg_gravy  is_mixedveg_gravy=1, protein='',
                                                   sub_category=mixed_veg_curry
    ncr        muton_curry              veg_gravy  is_mixedveg_gravy=1, protein='',
                                                   sub_category=mixed_veg_curry

The **misspelling is what hid them**. `audit_course_types.py` matches whole
`_`-tokens of a dish name against real dish words, and "chciken"/"chivken"/
"muton" are not words, so no name-based check could see any of them. The
importer's fold was blinded the same way: with `chciken` sitting in the
vocabulary as a "real" token, `chciken_mulligatawny` and `chicken_mulligatawny`
read as two different dishes instead of one misspelling.

The two NCR rows carry the bad-mapping fingerprint `ncr_bread_misfiles.py`
documents — blank `cuisine_family`, `key_ingredient` copied from the first word
of the name (`hyderabadi`, `muton`), dropped into a generic `mixed_veg_curry`
template. There the *attributes* are the fabrication and the name is the
evidence; in Bangalore's `hoskote_chciken_biryani` four columns agree on veg
biryani and only the misspelling disagrees, so the name is what gives way.
Each row is adjudicated on its own evidence:

* **rename** when the row's own columns name the dish and only the misspelling
  disagrees — `hoskote_chciken_biryani` -> `hoskote_veg_biryani`
  (`sub_category=north_veg_biryani`, `is_mixedveg_biryani=1`,
  `key_ingredient=mixed_vegetables`). Nothing else is named `hoskote_*`.
* **remove** when the corrected spelling duplicates a dish the city already
  carries properly — `chciken_kebab` (Bangalore has `chicken_kebab`:
  `nonveg_main`, `is_nonveg_dry`, protein chicken) and `hyderabadi_chivken`
  (NCR has `hyderabadi_chicken_curry` AND `hyderabadi_chicken_masala`, both
  `chicken_north_masala`). Keeping either would mean inventing six attributes
  for a dish the city already has under a correct name. This is the
  `jaipuri_paneer` adjudication from `ncr_bread_misfiles.py`.
* **re-file** when the corrected spelling is NOT a duplicate and the name
  supports the attributes — `muton_curry` -> `mutton_curry`, moved to
  `nonveg_main` with `primary_protein=mutton`. NCR carries no other mutton, so
  removing it would drop the dish Siemens' menu asks for; and course_type,
  protein and cuisine all follow from the name rather than being guessed.
  `sub_category` takes the protein-prefix convention `seafood_taxonomy.py`
  established when it coined `fish_north_masala` from `chicken_north_masala`.

`mutton` is already in `constants.NONVEG_PROTEINS`, so once re-filed the row is
correctly confined to `nonveg_main` by `PoolBuilder._nonveg_mask`.

Idempotent; re-run after any re-import of either city.
`tests/data/test_misspelled_protein_names.py` fails if the corrections are
missing, and pins the general guard: no dish name in any city may still contain
a misspelled protein word.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd

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


ROOT = Path(__file__).resolve().parent.parent
CITY_DIR = ROOT / "data" / "raw" / "city_items"

#: Misspellings of an animal-protein word. These are the ones that matter: a
#: misspelled protein makes a row invisible to every name-based audit AND lets a
#: meat-named dish sit in a vegetarian pool. Keys are whole snake_case tokens.
PROTEIN_TYPOS = {
    "chciken": "chicken", "chcken": "chicken", "chiceken": "chicken",
    "chikcen": "chicken", "chickem": "chicken", "chivken": "chicken",
    "chikken": "chicken", "chikan": "chicken",
    "muton": "mutton", "mutten": "mutton",
    "fsh": "fish", "prwan": "prawn", "pran": "prawn",
    "egss": "egg", "eeg": "egg",
}

PROTEIN_TYPO_RE = re.compile(
    r"(?<![a-z0-9])(" + "|".join(sorted(PROTEIN_TYPOS)) + r")(?![a-z0-9])")

#: city slug -> {misspelled name: new name}. The row's own columns name the
#: dish; only the misspelling disagrees.
RENAME = {
    "bangalore": {"hoskote_chciken_biryani": "hoskote_veg_biryani"},
}

#: city slug -> {misspelled name: why it goes rather than gets fixed}
REMOVE = {
    "bangalore": {
        "chciken_kebab":
            "spelled correctly it duplicates chicken_kebab (nonveg_main, "
            "is_nonveg_dry, protein=chicken); as a veg starter its real name "
            "is unrecoverable",
    },
    "ncr": {
        "hyderabadi_chivken":
            "spelled correctly it duplicates hyderabadi_chicken_curry and "
            "hyderabadi_chicken_masala, both properly filed chicken_north_masala",
    },
}

#: city slug -> {misspelled name: the fields the corrected NAME supports}
REFILE = {
    "ncr": {
        "muton_curry": {
            "item": "mutton_curry",
            "course_type": "nonveg_main",
            "primary_protein": "mutton",
            "key_ingredient": "mutton",
            "cuisine_family": "north_indian",
            "sub_category": "mutton_north_masala",
        },
    },
}

#: veg flags a re-filed non-veg row must not keep
VEG_FLAGS_TO_CLEAR = ("is_mixedveg_gravy", "is_mixedveg_biryani",
                      "is_veg_starter", "is_veg_dry", "is_premium_veg",
                      "is_premium_veg_dry")

CITIES = ("bangalore", "pune", "chennai", "ncr")


def apply(df: pd.DataFrame, city: str):
    """Return (df, renamed, removed, refiled). Safe to call twice."""
    df = df.copy()
    city = city.strip().lower()

    def names():
        return df["item"].astype(str).str.strip().str.lower()

    renamed = []
    for old, new in RENAME.get(city, {}).items():
        hit = names() == old
        if not hit.any():
            continue
        if (names() == new).any():                       # pragma: no cover
            raise SystemExit(f"cannot rename {old} -> {new}: {new} exists")
        df.loc[hit, "item"] = new
        renamed.append((old, new))

    refiled = []
    for old, fields in REFILE.get(city, {}).items():
        hit = names() == old
        if not hit.any():
            continue
        new = fields["item"]
        if (names() == new).any():                       # pragma: no cover
            raise SystemExit(f"cannot re-file {old} -> {new}: {new} exists")
        for col, val in fields.items():
            if col in df.columns:
                df.loc[hit, col] = val
        for flag in VEG_FLAGS_TO_CLEAR:
            if flag in df.columns:
                df.loc[hit, flag] = 0
        refiled.append((old, new))

    removed = []
    for old in REMOVE.get(city, {}):
        hit = names() == old
        if hit.any():
            df = df[~hit]
            removed.append(old)
    return df.reset_index(drop=True), renamed, removed, refiled


def main(dry_run: bool = False):
    for city in CITIES:
        path = CITY_DIR / f"{city}.xlsx"
        if not path.exists():                            # pragma: no cover
            continue
        if not (RENAME.get(city) or REMOVE.get(city) or REFILE.get(city)):
            continue
        df = pd.read_excel(path)
        df.columns = [c.strip() for c in df.columns]
        before = len(df)
        out, renamed, removed, refiled = apply(df, city)

        for old, new in renamed:
            print(f"[{city}] renamed  {old} -> {new}")
        for old, new in refiled:
            print(f"[{city}] re-filed {old} -> {new} "
                  f"({REFILE[city][old]['course_type']}, "
                  f"{REFILE[city][old]['primary_protein']})")
        for old in removed:
            print(f"[{city}] removed  {old}")
            print(f"           {REMOVE[city][old]}")
        if not (renamed or removed or refiled):
            print(f"[{city}] nothing to do — corrections already applied")
            continue
        print(f"[{city}] {before} -> {len(out)} rows")
        if dry_run:
            continue
        _atomic_to_excel(out, path, index=False)
        print(f"[{city}] wrote {path.name}")
    if dry_run:
        print("[dry-run] nothing written")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    main(dry_run=ap.parse_args().dry_run)
