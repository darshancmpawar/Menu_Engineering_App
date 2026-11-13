"""Write the `item_style` column (flavoured rice + soup) into a city ontology xlsx.

Usage: python scripts/build_item_style.py bangalore
Style = exceptions[item] else by_sub_category[course_type][sub_category]; other rows blank.
Edits the workbook in place with openpyxl so the other columns/formatting are untouched.
"""
import json
import sys
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "data/configs/item_style.json").read_text(encoding="utf-8"))
EXC = {k: v for k, v in CFG["exceptions"].items() if not k.startswith("_")}


def main(city: str) -> None:
    path = ROOT / f"data/raw/city_items/{city}.xlsx"
    wb = openpyxl.load_workbook(path)
    ws = wb.worksheets[0]
    head = [c.value for c in ws[1]]
    col = {h: i for i, h in enumerate(head)}
    if "item_style" in col:
        out = col["item_style"] + 1
    else:
        out = len(head) + 1
        ws.cell(row=1, column=out, value="item_style")
    counts = {}
    for r in range(2, ws.max_row + 1):
        item = ws.cell(r, col["item"] + 1).value
        ct = ws.cell(r, col["course_type"] + 1).value
        sub = ws.cell(r, col["sub_category"] + 1).value
        kind = "rice" if ct == "rice" else "soup" if ct == "soup" else None
        style = None
        if kind:
            style = EXC.get(item) or CFG["by_sub_category"][kind].get(sub)
            counts[(kind, style)] = counts.get((kind, style), 0) + 1
        ws.cell(r, out, style)
    wb.save(path)
    for k in sorted(counts, key=str):
        print(k, counts[k])


if __name__ == "__main__":
    main(sys.argv[1])
