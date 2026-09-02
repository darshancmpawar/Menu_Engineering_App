#!/usr/bin/env python3
"""Fold the client's enriched workbooks into the city item lists.

The client returned `<city>_enriched_final.xlsx` for Bangalore, Chennai, NCR and
Pune (committed under `data/raw/source_workbooks/`). They are a genuine
improvement and they are NOT a drop-in replacement, so this merges rather than
overwrites.

WHAT THEY BRING, measured against the workbooks before this ran:

  * `item_color` 0% blank in all four (was 15.7% Bangalore, 35.7% NCR, 11.1%
    Pune). This is the backlog `docs/colours_to_confirm_by_family.csv` asked the
    client to answer, answered. Of the 5,186 Bangalore dishes coloured in both
    files only SIX disagree, and all six are rows `fill_item_colours.py` had
    just inferred — their value is the better one each time (`chicken_65` is
    red, not brown). That is a reviewed dataset, not a bulk fill.
  * `primary_protein` 0% blank (was ~77% everywhere), with a real vocabulary
    (`none` 4,073 · chicken 501 · chickpea 251 · paneer 231 · toor_dal 202).
    An explicit `none` is better than a blank: `ingredient_ban_rule` and every
    `primary_protein` selector can act on it.
  * `richness_score` a real 1-5 spread where ours was 98% zeros.
  * `spice_level` and `texture`, which the schema did not carry at all.
  * NCR's last 233 blank cuisines.

WHY IT IS A MERGE AND NOT A REPLACEMENT — the uploads are branched from a
snapshot taken before the last three commits, so replacing would silently undo:
`d_star_hospitality` and the other vendor/calendar rows would return to NCR's
`veg_gravy` pool; the `raitha` duplicates would return; twenty-one course fixes
would revert (ice cream, custard, jal jeera and mango Tang back to `veg_gravy`);
and Chennai's 56 plus Pune's 8 bare-integer `item_id`s would come back. So the
CURRENT workbook is the base and only values are taken across.

Their row edits are handled where they belong rather than here: the junk they
caught and we missed (three more Stryker sheet titles, `junglee_games`,
`new_vendor_at_manesar`, `non_veg_not_serving_due_to_navratri`, `june`,
`march`, …) is in `remove_generic_rows.py`, and their duplicate folds are in
`canonical_dish_spellings.py` — with two of their verdicts REVERSED, because
`mixed_fruit_crush` is a welcome drink and `mixed_fruit_custard` a dessert (two
dishes, not two spellings), and because their `rasgulla` -> `rasgulaa` keeps the
row that is both misspelled and misfiled as a `veg_gravy`.

CONFIDENCE IS NOT CERTAINTY. The enriched files carry `provenance`,
`confidence` and `chef_review` sheets. `item_color` is 0% blank but **720
Bangalore and 354 NCR values are low-confidence**, which is exactly what their
`chef_review` queue lists. `scripts/dump_chef_review.py` turns that into
`docs/chef_review_queue.csv` so the open question stays visible.

Only blanks are filled and only from a non-blank source value, except for the
columns listed in `OVERWRITE`, where the client's reviewed value wins outright.
Idempotent. `tests/data/test_enriched_merge.py`.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CITY_DIR = ROOT / "data" / "raw" / "city_items"
SOURCE_DIR = ROOT / "data" / "raw" / "source_workbooks"
sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling scripts
sys.path.insert(0, str(ROOT))                             # `src` for the guard
from city_list import CITIES  # noqa: E402

#: The client reviewed these, so their value replaces ours where they have one.
#: `item_color` is here because the six disagreements were all ours to lose;
#: `richness_score` because ours was 98% zeros and carries no information.
OVERWRITE = ("item_color", "richness_score")

#: Filled only where ours is blank — we do not overwrite a value we derived
#: definitionally (`primary_protein` drives `_nonveg_mask`) or one that a
#: correction script adjudicated (`cuisine_family` for the north-chicken rows).
FILL_BLANKS = ("primary_protein", "cuisine_family", "cuisine_family_region")

#: New columns the schema did not have. Added at the end so the existing column
#: order is untouched and every `[:134]` reader keeps working.
NEW_COLUMNS = ("spice_level", "texture")

#: Hyderabad has no enriched workbook of its own because it did not exist when
#: the client was given the files. It is SEEDED from Bangalore, so the enriched
#: values reach it by dish name from the merged Bangalore list; Quest's 101
#: additions keep whatever they had and are reported.
SEEDED_FROM = {"hyderabad": "bangalore"}


def _norm(value) -> str:
    """Normalise for comparison. `none` reads as BLANK, deliberately.

    The enriched files spell "this dish has no protein focus" as the literal
    string `none` — 4,073 of Bangalore's 6,143 rows — which is why their
    `primary_protein` is 0% blank where ours is 77%. That is a presentation
    difference, not information: a blank already means the same thing to every
    consumer, and writing `none` would put a matchable value into a column that
    `selector_frequency`, `ingredient_ban_rule` and `_nonveg_mask` all select
    on, where a rule naming it would read as a real ingredient.

    So only the 652 rows carrying an ACTUAL protein are taken across. The column
    stays "77% blank" on paper and gains exactly the information the enriched
    file added.
    """
    s = str(value).strip().lower()
    return "" if s in ("", "nan", "none") else s


def _atomic_to_excel(frame, path):
    tmp = Path(path).with_name(Path(path).name + ".tmp")
    frame.to_excel(tmp, index=False)
    tmp.replace(path)


def enriched_path(city: str) -> Path:
    return SOURCE_DIR / f"{city}_enriched_final.xlsx"


def load_enriched(city: str):
    """{dish: {column: value}} from the enriched workbook's `items` sheet."""
    path = enriched_path(city)
    if not path.is_file():
        return None
    d = pd.read_excel(path, sheet_name="items")
    d.columns = [c.strip() for c in d.columns]
    wanted = [c for c in (*OVERWRITE, *FILL_BLANKS, *NEW_COLUMNS) if c in d.columns]
    out = {}
    for _, r in d[["item", *wanted]].iterrows():
        out[_norm(r["item"])] = {c: r[c] for c in wanted}
    return out


def _refused(column: str, value, row) -> bool:
    """True when the enriched value must not be written to this row.

    One guard, for one failure mode the enriched pass has: it reads
    `primary_protein` off the dish NAME, and a name can lie about it. Two
    Bangalore rows prove it — `keema_veg_biryani` was given `mutton` (a VEG
    biryani; "keema" here is the soya kind, the same trap
    `misspelled_protein_names.py` and `nonveg_structural_flags.py` already
    document for twelve NCR keemas) and `red_velvet_pastry_egg_less` was given
    `egg`, which its own name denies.

    Both are worse than a blank, and not by a little: `PoolBuilder.build_pools`
    drops every `_nonveg_mask` row from every slot outside `NONVEG_SLOTS`, so a
    `rice` row carrying `mutton` leaves the rice pool and never joins a non-veg
    one. The dish becomes UNSERVABLE — the exact structural break
    `audit_course_types.unservable_rows` exists to catch.

    So a non-veg protein is only accepted on a row whose course is one the
    pools keep non-veg dishes in. That is `NONVEG_SLOTS` — **the set, not the
    singular `NONVEG_SLOT`**: there are two such courses, and reading the
    singular refuses a chicken broth its own protein, `nonveg_soup` being a
    real slot that Bangalore fills with 30 of them. Everything else the
    enriched file offers is taken as given.
    """
    if column != "primary_protein":
        return False
    from src.constants import NONVEG_PROTEINS, NONVEG_SLOTS
    return (_norm(value) in {_norm(p) for p in NONVEG_PROTEINS}
            and _norm(row.get("course_type")) not in {_norm(s) for s in NONVEG_SLOTS})


def merge(df: pd.DataFrame, enriched: dict):
    """Return (df, stats). Safe to call twice."""
    df = df.copy()
    for col in NEW_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    # Widen every target column to object first. `richness_score` and
    # `spice_level` are integers arriving into columns pandas has typed `str`
    # (or the reverse), and pandas 3 refuses the write rather than upcasting —
    # the same trap `normalize_item_ids.renumber` hit on an all-int id column.
    for col in (*OVERWRITE, *FILL_BLANKS, *NEW_COLUMNS):
        if col in df.columns:
            df[col] = df[col].astype(object)
    stats = {c: 0 for c in (*OVERWRITE, *FILL_BLANKS, *NEW_COLUMNS)}
    stats["unmatched"] = 0
    refused = []
    names = df["item"].map(_norm)
    for i, name in names.items():
        src = enriched.get(name)
        if src is None:
            stats["unmatched"] += 1
            continue
        for col in OVERWRITE:
            new = _norm(src.get(col))
            if new and new != _norm(df.at[i, col]):
                df.at[i, col] = src[col]
                stats[col] += 1
        for col in (*FILL_BLANKS, *NEW_COLUMNS):
            if col not in df.columns:
                continue
            if _norm(df.at[i, col]) == "" and _norm(src.get(col)) != "":
                if _refused(col, src[col], df.loc[i]):
                    refused.append((name, col, src[col],
                                    _norm(df.at[i, "course_type"])))
                    continue
                df.at[i, col] = src[col]
                stats[col] += 1
    stats["refused"] = refused
    return df, stats


def main(dry_run: bool = False) -> int:
    merged = {}
    for city in CITIES:
        path = CITY_DIR / f"{city}.xlsx"
        if not path.is_file():                                 # pragma: no cover
            continue
        df = pd.read_excel(path)
        df.columns = [c.strip() for c in df.columns]

        enriched = load_enriched(city)
        if enriched is None:
            donor = SEEDED_FROM.get(city)
            if donor is None or donor not in merged:
                print(f"[{city}] no enriched workbook and no donor — skipped")
                continue
            # Take the values from the DONOR's merged frame, by dish name.
            d = merged[donor]
            cols = [c for c in (*OVERWRITE, *FILL_BLANKS, *NEW_COLUMNS)
                    if c in d.columns]
            enriched = {_norm(r["item"]): {c: r[c] for c in cols}
                        for _, r in d[["item", *cols]].iterrows()}
            print(f"[{city}] no enriched workbook — taking values from {donor}")

        out, stats = merge(df, enriched)
        merged[city] = out
        refused = stats.pop("refused", [])
        changed = sum(v for k, v in stats.items() if k != "unmatched")
        detail = ", ".join(f"{k} {v}" for k, v in stats.items()
                           if v and k != "unmatched")
        print(f"[{city}] {changed} cell(s) merged"
              + (f" — {detail}" if detail else "")
              + f"; {stats['unmatched']} row(s) not in the enriched file")
        for nm, col, val, course in refused:
            print(f"    ! refused {col}={val!r} on {nm} ({course}) — a non-veg "
                  f"protein outside nonveg_main makes the dish unservable")
        if changed and not dry_run:
            _atomic_to_excel(out, path)
            print(f"[{city}] wrote {city}.xlsx")
    if dry_run:
        print("\n[dry-run] nothing written")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    sys.exit(main(dry_run=ap.parse_args().dry_run))
