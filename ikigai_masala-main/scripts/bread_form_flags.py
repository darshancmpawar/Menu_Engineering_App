#!/usr/bin/env python3
"""One bread flag, one meaning: `is_plain_phulka_chapathi`, in both directions.

Four clients state their bread rule as "chapati only" — AT&T ("chapathi and
flavour chapathi only"), Booking ("indian bread will be chapati daily"), Clario
("chapati twice a week, the other days special breads") and Citrix ("phulka or
chapati only") — and Pune's rulebook R36 makes the plain chapati a *staple*
exempt from the no-repeat rule. All of that reads one column, and the column was
wrong in both directions:

* **Set on dishes that are not a chapati.** NCR carried 19, from the mapping
  pipeline: `dhaba_chicken_curry`, `kolhapuri_chicken` and `egg_curry_masala`
  (not even breads), `jodhpuri_pulao`, `pav_bhaji`, `pao`, `fried_idli`,
  `bhelpuri`, four `poori`s, three `kulcha`s and two `paratha`s. Bangalore
  carried `amras_puri`, `bhel_puri` and `ragi_mudde`. A "chapati only" rule
  would have served a puri, a pav or a millet ball as the day's chapati.
* **Absent from dishes that are.** Every `chapati`-spelled row in every city was
  unflagged while its `chapatti`-spelled twin was flagged — the client menu
  imports and `expand_side_pools.py` wrote the source spelling and left the
  column blank, so `plain_chapati`, `garlic_chapati` and the seven curated
  flavoured chapatis were invisible to every rule about chapatis.
* **Inconsistent across the roti family.** `akki_roti`, `ragi_roti`,
  `jowar_roti`, `bajra_roti`, `rumali_roti` and `tandoori_roti` were unflagged
  while `joleda_roti`, `rava_roti`, `coorg_roti`, `romali_roti` and the three
  `tandoor_*_roti` were flagged. The two groups are the same kinds of bread, so
  one of the readings is wrong; the majority is that a millet, rava, tandoor or
  rumali roti is a *special* bread — which is also how Clario's own menu lists
  them ("Rumali Roti, Kerala Parotta, Puri, Dosa, Pav, Akki Rotti") — and that
  is the reading applied.

So the flag is defined from the dish NAME, and applied in both directions the
way `seafood_taxonomy.py` defines `is_fish_dish`: a flag that is only ever set
drifts. It means **the everyday wheat tawa flatbread** — a chapati, a phulka, or
a plain/flavoured wheat roti — and nothing else:

* a `chapati`/`chapatti`/`chapathi`/`phulka`/`fulka` token  → set
* a `roti`/`rotti` token with no other-family qualifier     → set
* a competing bread form or another course in the name      → clear
* anything else                                             → clear

Only `course_type == bread` rows can gain the flag; every other row loses it,
which is what removes it from the three NCR curries and the pulao.

Runs across every city. Idempotent; re-run after any re-import or client menu
import — an importer writes only what a dish name supports and leaves this
column blank. `tests/data/test_bread_form_flags.py`.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CITY_DIR = ROOT / "data" / "raw" / "city_items"
CITIES = ("bangalore", "pune", "chennai", "ncr")

FLAG = "is_plain_phulka_chapathi"

#: The dish IS a chapati or phulka, however it is spelled or flavoured.
CHAPATI_TOKENS = ("chapati", "chapatti", "chapathi", "phulka", "fulka")

#: A roti is the same bread under another name — but only a wheat one.
ROTI_TOKENS = ("roti", "rotti")

#: Qualifiers that make a "roti" a different bread. Every one of these is a
#: grain other than wheat, a tandoor bread, or a named speciality, and the
#: ontology already treats the majority of them as NOT a chapati (see the
#: module docstring).
OTHER_ROTI_FAMILY = (
    "akki", "ragi", "jowar", "jolada", "joleda", "jaloda", "bajra", "bajri",
    "rava", "multigrain", "coorg", "missi", "missa", "makki", "makai",
    "rumali", "romali", "roomali", "tandoor", "tandoori",
)

#: A name carrying one of these names a DIFFERENT bread form or another course
#: entirely, so the row is not a chapati even when a chapati token is also
#: present — `jeera_chapati_dosa` and `triangle_chapati_puri` are combination
#: cells a menu import split badly, not chapatis.
COMPETING_FORMS = (
    "dosa", "dosai", "puri", "poori", "bhelpuri", "bhelpoori", "paratha",
    "parantha", "parotta", "kulcha", "naan", "kulche", "appam", "pav", "pao",
    "idli", "idly", "bhel", "mudde", "bhaji", "bhatura", "bhature", "thepla",
    "uttapam", "uthappam", "poha", "upma",
)


def _atomic_to_excel(frame, path, **kw):
    """Write via a temp file + rename: `to_excel` truncates the target before
    streaming into it, so an interrupted run leaves a 0-byte workbook."""
    p = Path(path)
    tmp = p.with_name(p.name + ".tmp")
    kw.setdefault("index", False)
    frame.to_excel(tmp, **kw)
    tmp.replace(p)


def _tokens(name: str) -> set:
    return {t for t in re.split(r"[^a-z0-9]+", str(name).strip().lower()) if t}


def is_chapati(name: str, course: str) -> bool:
    """True when *name* is the everyday wheat tawa flatbread.

    ``course`` gates it: a chapati is always filed as a bread, and a bread flag
    on a curry or a pulao is exactly the defect this script exists to remove.
    """
    if str(course).strip().lower() != "bread":
        return False
    toks = _tokens(name)
    if toks & set(COMPETING_FORMS):
        return False
    if toks & set(CHAPATI_TOKENS):
        return True
    if toks & set(ROTI_TOKENS):
        return not (toks & set(OTHER_ROTI_FAMILY))
    return False


def apply(df: pd.DataFrame):
    """Return ``(df, set_rows, cleared_rows)``. Safe to call twice."""
    df = df.copy()
    if FLAG not in df.columns:                           # pragma: no cover
        return df, [], []
    want = df.apply(
        lambda r: is_chapati(r.get("item", ""), r.get("course_type", "")),
        axis=1)
    have = pd.to_numeric(df[FLAG], errors="coerce").fillna(0).astype(int) == 1
    gained = df.loc[want & ~have, "item"].astype(str).tolist()
    lost = df.loc[~want & have, "item"].astype(str).tolist()
    df[FLAG] = want.astype(int)
    return df, gained, lost


def main(dry_run: bool = False) -> int:
    total = 0
    for city in CITIES:
        path = CITY_DIR / f"{city}.xlsx"
        if not path.exists():                            # pragma: no cover
            continue
        df = pd.read_excel(path)
        df.columns = [c.strip() for c in df.columns]
        out, gained, lost = apply(df)
        if not gained and not lost:
            print(f"[{city}] already correct "
                  f"({int(out[FLAG].sum())} chapati/phulka rows)")
            continue
        for name in sorted(gained):
            print(f"[{city}] + {name}")
        for name in sorted(lost):
            print(f"[{city}] - {name}")
        total += len(gained) + len(lost)
        if not dry_run:
            _atomic_to_excel(out, path)
            print(f"[{city}] wrote {path.name} "
                  f"(+{len(gained)} / -{len(lost)}) -> "
                  f"{int(out[FLAG].sum())} chapati/phulka rows")
    print(f"\n{total} flag correction(s)")
    if dry_run:
        print("[dry-run] nothing written")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    sys.exit(main(dry_run=ap.parse_args().dry_run))
