"""The menu table as an interactive Streamlit component.

`ui.planner_view.menu_table_html` renders the same table as static HTML and
still does, for the Excel export path and for anything that only needs to
*show* a plan. This module is the interactive one: its cells are selectable and
"Regenerate selected" replaces the old regenerate expander, which asked the
planner to re-pick from a dropdown the slots they were already looking at.

The component itself is a plain HTML file (`ui/menu_table/index.html`) talking
to Streamlit over the documented postMessage protocol — no npm, no bundler, no
node in the repo. See the comment at the top of that file.

Selection lives inside the component, not in Streamlit session state: a rerun
per click would cost a round trip for every cell a planner picks. Only pressing
Regenerate sends a value back, so the page reruns once per regenerate.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import List, Optional

import streamlit.components.v1 as components

from ui.formatters import display_label_for_slot_id, format_item_for_ui

_DIR = Path(__file__).parent / "menu_table"
_component = components.declare_component("ikigai_menu_table", path=str(_DIR))

#: Rough height of one table row, for the iframe's initial height. The
#: component measures itself and reports the real height straight after, so
#: this only has to stop the first paint from being clipped.
_ROW_PX = 41
_CHROME_PX = 150


#: The colour initial the solver appends, e.g. `veg_fried_rice(Y)`. Same
#: pattern `format_item_for_ui` strips, kept next to it so the two cannot
#: disagree about what a suffix looks like.
_COLOR_SUFFIX = re.compile(r"\(([A-Z])\)\s*$")


def _color_key(item: str) -> str:
    m = _COLOR_SUFFIX.search(item or "")
    return m.group(1) if m else ""


def day_cells(plan: dict, dates: List[str], day_types: dict,
              nonveg: Optional[dict] = None,
              off_days: Optional[set] = None,
              pinned: Optional[set] = None,
              warned: Optional[set] = None,
              modified: Optional[set] = None,
              regions: Optional[dict] = None,
              issues: Optional[set] = None) -> dict:
    """Shape a plan block into the component's arguments.

    Pure: takes plain data, returns plain data, touches no Streamlit. The
    membership sets are keyed `"<slot_id>|<iso date>"`, the same key the
    component sends back, so a caller never has to build two spellings of the
    same cell.
    """
    nonveg, off_days = nonveg or {}, off_days or set()
    pinned, warned = pinned or set(), warned or set()
    modified, issues = modified or set(), issues or set()
    regions = regions or {}

    days = []
    for iso in dates:
        try:
            label = dt.date.fromisoformat(iso).strftime("%a %d")
        except ValueError:
            label = iso
        theme = str(day_types.get(iso, "")).strip().lower()
        days.append({
            "iso": iso,
            "label": label,
            "theme": theme,
            "theme_label": theme.replace("_", " ").title() or "—",
            "region": regions.get(iso),
            "has_issue": iso in issues,
        })

    slot_ids: List[str] = []
    for iso in dates:
        for slot_id in (plan.get(iso) or {}):
            if slot_id not in slot_ids:
                slot_ids.append(slot_id)

    rows = []
    for slot_id in slot_ids:
        cells = {}
        for iso in dates:
            raw = (plan.get(iso) or {}).get(slot_id)
            if iso in off_days:
                cells[iso] = {"off": True, "name": "Not served"}
                continue
            if not raw:
                cells[iso] = {"off": True, "name": "—"}
                continue
            k = f"{slot_id}|{iso}"
            cells[iso] = {
                "name": format_item_for_ui(str(raw)),
                "color": _color_key(str(raw)),
                "nonveg": slot_id in (nonveg.get(iso) or set()),
                "pinned": k in pinned,
                "warn": k in warned,
                "modified": k in modified,
                "title": str(raw),
            }
        rows.append({
            "id": slot_id,
            "label": display_label_for_slot_id(slot_id),
            "shared": False,
            "cells": cells,
        })
    return {"days": days, "rows": rows}


def menu_table(block: dict, *, title: str, meta: str = "", hint: str = "",
               explain: Optional[dict] = None, reset_token: str = "",
               key: Optional[str] = None) -> Optional[dict]:
    """Render one service's table. Returns the regenerate request, or None.

    The return is `{"action": "regenerate", "cells": ["<slot>|<iso>", …]}` —
    exactly the cells the planner ticked, which is the shape `/regenerate`
    already takes as its replace mask.
    """
    args = day_cells(
        block.get("plan", {}), block.get("plan_dates", []),
        block.get("day_types", {}), block.get("nonveg"), block.get("off_days"),
        pinned=block.get("pinned"), warned=block.get("warned"),
        modified=block.get("modified"), regions=block.get("regions"),
        issues=block.get("issues"),
    )
    height = _CHROME_PX + _ROW_PX * (len(args["rows"]) + 1)
    return _component(
        title=title, meta=meta, hint=hint,
        days=args["days"], rows=args["rows"],
        explain=explain or {}, reset_token=reset_token,
        default=None, key=key, height=height,
    )
