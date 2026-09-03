#!/usr/bin/env python3
"""Collect the enriched workbooks' open questions into one reviewable list.

`merge_enriched_ontology.py` takes the client's `item_color` outright, because
of the 5,186 Bangalore dishes coloured in both files only six disagreed and all
six were ours to lose. That is the right call for the column as a whole and it
is NOT a claim about every cell in it: the enriched files ship their own
`confidence` sheet saying so, and their own `chef_review` sheet listing the rows
they are least sure of — **720 Bangalore and 354 NCR colours** arrived marked
low confidence.

Those rows are now in the city lists, indistinguishable from the 5,000 the
client verified. A colour is not cosmetic — `MenuSolver._add_color_constraints`
counts distinct colours per day and caps repeats — so a wrong one quietly shapes
which dishes can share a plate. The question is open, and an open question that
lives only inside a source workbook nobody opens is a closed one.

So this writes `docs/chef_review_queue.csv`: every row the client flagged, with
what the merge actually wrote for it, ordered lowest-confidence first. It is a
REPORT — it changes no data and decides nothing. Answering it means editing the
city workbook (or the correction scripts) with a real verdict.

The queue reflects the enriched files rather than the current workbooks on one
point deliberately: a row here whose colour we have since changed by hand still
belongs in the list, with both values shown, because the disagreement is exactly
what a reviewer should see.

Usage:
    python scripts/dump_chef_review.py [--check]

``--check`` re-derives the CSV and fails if the committed one is stale, the same
contract `dump_client_rules_index.py` uses.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CITY_DIR = ROOT / "data" / "raw" / "city_items"
SOURCE_DIR = ROOT / "data" / "raw" / "source_workbooks"
REPORT = ROOT / "docs" / "chef_review_queue.csv"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from city_list import CITIES  # noqa: E402

#: What the enriched `chef_review` sheet carries per row, beyond `item`.
REVIEW_COLUMNS = ("course_type", "item_color", "richness_score",
                  "spice_level", "texture", "item_color__confidence")


def _norm(value) -> str:
    s = str(value).strip().lower()
    return "" if s in ("", "nan", "none") else s


def collect(city: str) -> pd.DataFrame:
    """The city's flagged rows, joined to what its workbook now holds.

    Returns an empty frame for a city with no enriched workbook — Hyderabad has
    none (it did not exist when the client was given the files), and its values
    reach it from Bangalore by dish name, so Bangalore's queue covers it.
    """
    src = SOURCE_DIR / f"{city}_enriched_final.xlsx"
    if not src.is_file():
        return pd.DataFrame()
    try:
        flagged = pd.read_excel(src, sheet_name="chef_review")
    except ValueError:                                     # pragma: no cover
        return pd.DataFrame()                              # no such sheet
    flagged.columns = [c.strip() for c in flagged.columns]

    live = pd.read_excel(CITY_DIR / f"{city}.xlsx")
    live.columns = [c.strip() for c in live.columns]
    now = {_norm(r["item"]): r for _, r in live.iterrows()}

    rows = []
    for _, r in flagged.iterrows():
        name = _norm(r.get("item"))
        current = now.get(name)
        rows.append({
            "city": city,
            "item": name,
            "course_type": _norm(r.get("course_type")),
            "flagged_color": _norm(r.get("item_color")),
            # Blank when the dish is not in the list at all — a row the client
            # reviewed that a removal or a spelling fold has since taken out.
            # Worth showing rather than dropping: it says the two files have
            # diverged on more than a colour.
            "current_color": _norm(current.get("item_color")) if current is not None else "",
            "in_city_list": "yes" if current is not None else "no",
            "confidence": r.get("item_color__confidence"),
            "richness_score": r.get("richness_score"),
            "spice_level": r.get("spice_level"),
            "texture": _norm(r.get("texture")),
        })
    return pd.DataFrame(rows)


def build() -> pd.DataFrame:
    frames = [f for f in (collect(c) for c in CITIES) if not f.empty]
    if not frames:                                         # pragma: no cover
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    # Lowest confidence first: the top of the file is where a reviewer's time
    # buys the most. Ties broken by city then dish so the CSV is stable across
    # runs — an unstable report shows up as a diff on every invocation and
    # stops being read.
    return out.sort_values(
        ["confidence", "city", "item"], kind="mergesort"
    ).reset_index(drop=True)


def main(check: bool = False) -> int:
    out = build()
    if out.empty:                                          # pragma: no cover
        print("no chef_review sheets found — nothing to write")
        return 0
    text = out.to_csv(index=False)
    if check:
        if not REPORT.is_file():
            print(f"{REPORT} is missing — run without --check", file=sys.stderr)
            return 1
        if REPORT.read_text(encoding="utf-8") != text:
            print(f"{REPORT} is stale — re-run without --check", file=sys.stderr)
            return 1
        print(f"{REPORT} is current ({len(out)} row(s))")
        return 0
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(text, encoding="utf-8")
    by_city = out.groupby("city").size().to_dict()
    print(f"wrote {REPORT.relative_to(ROOT)}: {len(out)} row(s) "
          + ", ".join(f"{c} {n}" for c, n in sorted(by_city.items())))
    missing = int((out["in_city_list"] == "no").sum())
    if missing:
        print(f"  ({missing} of them are no longer in their city's list)")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    sys.exit(main(check=ap.parse_args().check))
