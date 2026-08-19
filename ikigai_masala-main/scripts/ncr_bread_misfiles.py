#!/usr/bin/env python3
"""**NCR only.** Curries, dals and a salad were filed as ``course_type=bread``.

The NCR mapping pipeline put a batch of gravy/dry dishes into the bread slot —
``paneer_jaipuri`` (a paneer curry, ``primary_protein=paneer``) sat in the bread
pool with ``sub_category=flavoured_paratha``, so a counter could serve it as the
day's roti. Twelve rows are affected, all carrying a blank ``cuisine_family`` and
a nonsense ``key_ingredient`` lifted from the first word of the name
(``key_ingredient=jaipuri``), which is the fingerprint of the bad mapping.

`course_type` picks the slot pool, so a misfile makes a dish servable in the
wrong position — the same class of bug `scripts/audit_course_types.py` guards,
which its name-token matcher missed here because "jaipuri"/"jodhpuri" are place
names, not dish words.

Two actions:
  * **Re-file** a real dish to the category it belongs to (it then also deepens
    that category's pool, which is where NCR is actually thin).
  * **Remove** a row that is a duplicate of one already present, or that names a
    category rather than a dish (``breads``) — the rule
    `scripts/remove_generic_rows.py` applies elsewhere.

Idempotent; re-run after any NCR re-import. `test_ncr_bread_misfiles.py`
fails if any of them creep back into the bread pool.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
NCR = ROOT / "data" / "raw" / "city_items" / "ncr.xlsx"

# item -> the course_type it actually belongs to.
REFILE = {
    "paneer_jaipuri": "veg_gravy",          # paneer curry, Jaipuri style
    "jaipuri_bhindi_masala": "veg_dry",     # okra dry (the gravy version exists)
    "soyawadi_jaipuri": "veg_dry",          # soya chunks dry
    "jodhpuri_aloo": "veg_dry",             # potato dry
    "jodhpuri_dal_tadka": "dal",            # a dal, plainly
    "kolhapuri_mix_veg_gravy": "veg_gravy",  # the name says gravy
    "aloo_kolahpuri": "veg_gravy",          # potato curry
    "aloo_dum_bhojpuri": "veg_gravy",       # dum aloo
    "ghiya_vadi_rasmissi": "veg_gravy",     # bottle-gourd + vadi curry
    "lachha_onion": "salad",                # sliced-onion side
}

# item -> why it goes entirely.
REMOVE = {
    "jaipuri_paneer": "duplicate of paneer_jaipuri (same dish, same protein)",
    "breads": "names the category, not a dish (cf. remove_generic_rows.py)",
}

# Correct the junk key_ingredient the mapper left behind on the re-filed rows.
KEY_INGREDIENT = {
    "paneer_jaipuri": "paneer",
    "jaipuri_bhindi_masala": "okra",
    "soyawadi_jaipuri": "soya",
    "jodhpuri_aloo": "potato",
    "jodhpuri_dal_tadka": "dal",
    "kolhapuri_mix_veg_gravy": "mixed_vegetables",
    "aloo_kolahpuri": "potato",
    "aloo_dum_bhojpuri": "potato",
    "ghiya_vadi_rasmissi": "bottle_gourd",
    "lachha_onion": "onion",
}

# A re-filed row must not keep bread-only markers.
_BREAD_FLAGS = ["is_bread", "is_maida_bread", "is_rice_bread", "is_tandoor",
                "is_oil_based_bread", "is_dosa", "is_dosa_family",
                "is_plain_phulka_chapathi"]
_BREAD_SUBCATS_OK = {"veg_gravy": "mixed_veg_curry", "veg_dry": "mixed_veg_dry",
                     "dal": "dal", "salad": "salad"}


def _norm(s) -> str:
    return str(s).strip().lower() if s is not None else ""


def fix(df: pd.DataFrame) -> pd.DataFrame:
    names = df["item"].map(_norm)

    drop_mask = names.isin(REMOVE)
    out = df[~drop_mask].copy()

    names = out["item"].map(_norm)
    for item, target in REFILE.items():
        m = names == item
        if not m.any():
            continue
        out.loc[m, "course_type"] = target
        if "sub_category" in out.columns:
            out.loc[m, "sub_category"] = _BREAD_SUBCATS_OK.get(target, target)
        if "key_ingredient" in out.columns and item in KEY_INGREDIENT:
            out.loc[m, "key_ingredient"] = KEY_INGREDIENT[item]
        for f in _BREAD_FLAGS:
            if f in out.columns:
                out.loc[m, f] = 0
    return out


def main(dry_run=False):
    df = pd.read_excel(NCR)
    df.columns = [c.strip() for c in df.columns]
    before = (df["course_type"].map(_norm) == "bread").sum()
    out = fix(df)
    after = (out["course_type"].map(_norm) == "bread").sum()

    names = df["item"].map(_norm)
    print(f"NCR bread rows: {before} -> {after}")
    for item, target in REFILE.items():
        if (names == item).any():
            print(f"  re-filed  {item:<24} bread -> {target}")
    for item, why in REMOVE.items():
        if (names == item).any():
            print(f"  removed   {item:<24} {why}")
    if not dry_run:
        _atomic_to_excel(out, NCR, index=False)
        print(f"wrote {NCR.name}")
    else:
        print("[dry-run] nothing written")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    main(dry_run=a.dry_run)


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
