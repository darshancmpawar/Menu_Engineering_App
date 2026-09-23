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

**`primary_protein` is folded too, and soya is why.** That column was left alone
while only `key_ingredient` mattered; it stopped being enough the moment a rule
had to say "not two dishes of the same protein on one plate", because soya is
the one protein the ontology spells four ways and NCR is split nearly in half:
`primary_protein` soya 37 / soy 21, and `key_ingredient` soya 29 / soy 10 /
soyabean 3 / soyabin, soyawadi, soybean 1 each. Against 272 clean `soy` rows in
the other four cities, so `soy` is canonical by a wide margin. A variety rule
reading the column raw would see two unrelated ingredients and let a soya chaap
sit beside a soya keema; `customisation/client rules/siemens.json` already carried
BOTH spellings as adjacent `any_of` selectors, which is a config working around
a data defect.

**Twelve NCR rows also name a cooking style where the protein belongs**, the
first-word-of-the-name fingerprint of the mapping pipeline that
`course_type_corrections.py` documents for `pav`: `chaap_lababdar` is
`key_ingredient: chaap`, `malai_soya_chaap` is `malai`, `rara_chaap` is `rara`.
Chaap IS a soy product — all seven `chaap` rows carry `primary_protein: soya`
independently — so those are named row by row in ROW_KEY_INGREDIENT rather than
pattern-matched. `ghiya_soya` is deliberately left as `ghiya`: bottle gourd is a
real co-ingredient there and the protein is already recorded in its own column.

Idempotent; re-run after any re-import.
"""
from __future__ import annotations

import argparse
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

#: variant `key_ingredient` -> the canonical value the ontology already uses.
FOLD = {
    "channa_dal": "chana_dal",
    "gram_dal": "chana_dal",
    "cottage_cheese": "paneer",
    "soppu_moong": "green_moong",
    "allesande": "black_eyed_pea",
    "kofta_made_from_lentil": "toor_dal",
    # `rajma` IS the kidney bean, and `kidney_bean` is the value the other four
    # cities and the client's own protein list use. NCR spelled it the Hindi
    # way on its one row, which made that dish invisible to a
    # `key_ingredient: kidney_bean` selector — the exact cost this table
    # exists to remove.
    "rajma": "kidney_bean",
    # Soya, spelled four ways in NCR alone. `soy` is canonical by majority
    # (272 rows across the other four cities). `soyawadi` is soya wadi —
    # the nugget, not a different bean.
    "soya": "soy",
    "soyabean": "soy",
    "soyabin": "soy",
    "soybean": "soy",
    "soyawadi": "soy",
}

#: Variant `primary_protein` -> canonical. Same argument as FOLD, one column
#: over: a rule that says "not two dishes of the same protein today" reads this
#: column, so two spellings of one protein read as two proteins.
FOLD_PROTEIN = {
    "soya": "soy",
    "soyabean": "soy",
    "soyabin": "soy",
    "soybean": "soy",
    "soyawadi": "soy",
}

#: `(item, current key_ingredient) -> canonical` for a row whose key ingredient
#: column holds a cooking style or a vessel instead of the protein. Named row
#: by row, with the current value in the key, so a re-run is a no-op and a row
#: someone has since corrected by hand is never overwritten.
ROW_KEY_INGREDIENT = {
    # Chaap is a soy product; every one of these carries primary_protein soya.
    ("chaap_dhaba", "chaap"): "soy",
    ("chaap_lababdar", "chaap"): "soy",
    ("chaap_tak_a_tak", "chaap"): "soy",
    ("chaap_tikka_biryani", "chaap"): "soy",
    ("chaap_tikka_masala", "chaap"): "soy",
    ("masala_chaap_dhabha_style", "chaap"): "soy",
    ("tawa_chaap", "chaap"): "soy",          # tawa is the griddle
    ("kadahi_chaap", "kadahi"): "soy",       # kadai is the wok
    ("malai_soya_chaap", "malai"): "soy",    # malai is the cream finish
    ("rara_chaap", "rara"): "soy",           # rara is the style
    ("rogani_chaap", "rogani"): "soy",       # as in rogan josh
    ("chilli_soya_chunk_gravy", "chilli"): "soy",
    ("nurtri_soya_chunks_gravy", "nurtri"): "soy",   # nutrela = soy chunks
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


def _fold_column(df: pd.DataFrame, column: str, table: dict) -> int:
    """Rewrite variant values of one column in place. Returns rows changed."""
    if column not in df.columns:
        return 0
    col = df[column].map(_norm)
    n = 0
    for variant, canonical in table.items():
        mask = col == variant
        if mask.any():
            for item in df.loc[mask, "item"].astype(str):
                print(f"    {item}: {column} {variant} -> {canonical}")
            df.loc[mask, column] = canonical
            n += int(mask.sum())
    return n


def _fix_rows(df: pd.DataFrame) -> int:
    """Apply the named per-row key_ingredient verdicts. Returns rows changed."""
    if "key_ingredient" not in df.columns:
        return 0
    items = df["item"].map(_norm)
    ki = df["key_ingredient"].map(_norm)
    n = 0
    for (item, current), canonical in ROW_KEY_INGREDIENT.items():
        mask = (items == item) & (ki == current)
        if mask.any():
            print(f"    {item}: key_ingredient {current} -> {canonical}")
            df.loc[mask, "key_ingredient"] = canonical
            n += int(mask.sum())
    return n


def fold(df: pd.DataFrame) -> int:
    """Standardise both protein columns in place. Returns rows changed."""
    return (_fold_column(df, "key_ingredient", FOLD)
            + _fold_column(df, "primary_protein", FOLD_PROTEIN)
            + _fix_rows(df))


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
            _atomic_to_excel(df, path, index=False)
            print(f"  wrote {path.name}")
        elif dry_run:
            print("  [dry-run] nothing written")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--city")
    main(dry_run=ap.parse_args().dry_run, city=ap.parse_args().city)
