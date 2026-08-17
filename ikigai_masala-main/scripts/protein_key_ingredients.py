#!/usr/bin/env python3
"""Standardise the `key_ingredient` vocabulary for protein sources.

The client supplied a list of the protein sources they want on the daily menu
(choley, rajma, kala chana, lobia, moong, masoor, urad, sprouts, soya, paneer,
tofu, the dal family, besan chilla, peanut chaat, khichdi, ghugni...). The rule
that enforces it selects on **`key_ingredient`**, so a dish only counts if that
column names its pulse.

Mostly it already does — 651 rows across flavoured rice / veg_gravy / veg_dry /
salad / dal carry one of sixteen clean values. But a handful of dishes name the
same protein a second way, and those rows are invisible to a `key_ingredient`
selector even though the dish is exactly what the client asked for:

    channa_dal              cholar_dalna                    -> chana_dal
    gram_dal                amti_channa_dal                 -> chana_dal
    cottage_cheese          two salads with cottage cheese  -> paneer
    soppu_moong             soppu_moong_palya               -> green_moong
    allesande               allesande_kalu_palya (cowpea)   -> black_eyed_pea
    kofta_made_from_lentil  paruppu_urundai_kuzhambu        -> toor_dal

Each is a spelling/regional variant of a value the ontology already uses, so
this is a *vocabulary* fix, not a reclassification: no dish changes what it is,
and no dish moves category.

Deliberately NOT folded: `horse_gram`, `avarekalu`, `chikkudikayi`,
`broad_beans` and `cluster_beans`. Those are real pulses but they are their own
ingredients, not variant spellings of anything on the client's list — folding
them would misname the dish to make a rule fire. They are listed in
REGIONAL_PULSES so the client can decide whether the rule should count them.

Idempotent; re-run after any re-import.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CITY_DIR = ROOT / "data" / "raw" / "city_items"

#: variant `key_ingredient` -> the canonical value the ontology already uses.
FOLD = {
    "channa_dal": "chana_dal",
    "gram_dal": "chana_dal",
    "cottage_cheese": "paneer",
    "soppu_moong": "green_moong",
    "allesande": "black_eyed_pea",
    "kofta_made_from_lentil": "toor_dal",
}

#: The canonical protein-source vocabulary, i.e. the client's list expressed in
#: `key_ingredient` values. This is what the rule selects on.
PROTEIN_KEY_INGREDIENTS = [
    "chickpea",        # choley, kabuli chana, kala/black chana, chana salad
    "kidney_bean",     # rajma, rajma salad
    "black_eyed_pea",  # lobia
    "green_moong",     # green moong, moong salad
    "moong_dal",       # moong dal
    "masoor_dal",      # masoor dal, whole masoor
    "toor_dal",        # toor dal
    "chana_dal",       # chana dal
    "urad_dal",        # urad dal, whole urad
    "urad",
    "mixed_dal",       # mixed dal, panchmel
    "dal",             # the generic dal marker
    "paneer",          # paneer
    "soy",             # soya chunks, soya keema, tofu
    "peanut",          # peanut chaat
    "besan",           # besan chilla
]

#: Real pulses that are NOT on the client's list and are not variants of
#: anything on it. Left alone; surfaced so the client can opt them in.
REGIONAL_PULSES = [
    "horse_gram",     # huruli kaalu
    "avarekalu",      # hyacinth / field beans
    "chikkudikayi",   # broad beans (Telugu)
    "broad_beans",
    "cluster_beans",  # gavar
]

SLOTS = ["rice", "veg_gravy", "veg_dry", "salad", "dal"]


def _norm(s) -> str:
    return str(s).strip().lower() if s is not None else ""


def fold(df: pd.DataFrame) -> int:
    """Rewrite variant key_ingredient values in place. Returns rows changed."""
    if "key_ingredient" not in df.columns:
        return 0
    ki = df["key_ingredient"].map(_norm)
    n = 0
    for variant, canonical in FOLD.items():
        mask = ki == variant
        if mask.any():
            for item in df.loc[mask, "item"].astype(str):
                print(f"    {item}: {variant} -> {canonical}")
            df.loc[mask, "key_ingredient"] = canonical
            n += int(mask.sum())
    return n


def report(df: pd.DataFrame) -> None:
    ct = df["course_type"].map(_norm)
    sub = df[ct.isin(SLOTS)]
    ki = sub["key_ingredient"].map(_norm)
    hit = ki.isin(PROTEIN_KEY_INGREDIENTS)
    print(f"    protein-source dishes in the five slots: {int(hit.sum())} "
          f"of {len(sub)}")
    for slot in SLOTS:
        m = ct[ct.isin(SLOTS)].eq(slot)
        print(f"      {slot:<10} {int((m & hit).sum()):>4} of {int(m.sum()):>4}")


def main(dry_run=False, city=None):
    cities = [city] if city else sorted(p.stem for p in CITY_DIR.glob("*.xlsx"))
    for name in cities:
        path = CITY_DIR / f"{name}.xlsx"
        if not path.exists():
            print(f"{name}: no workbook, skipped")
            continue
        df = pd.read_excel(path)
        df.columns = [c.strip() for c in df.columns]
        print(f"\n=== {name} ===")
        n = fold(df)
        print(f"  folded {n} row(s)")
        report(df)
        if n and not dry_run:
            df.to_excel(path, index=False)
            print(f"  wrote {path.name}")
        elif dry_run:
            print("  [dry-run] nothing written")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--city")
    main(dry_run=ap.parse_args().dry_run, city=ap.parse_args().city)
