"""The menu table as an interactive Streamlit component.

`ui.planner_view.menu_table_html` renders the same table as static HTML. The
planner no longer calls it — this module replaced it, and "Regenerate selected"
replaced the old regenerate expander, which asked the planner to re-pick from a
dropdown the slots they were already looking at. It is kept as the fallback
renderer while the component is being signed off; once it is, that function and
its tests go, since the behaviour they cover (off days labelled rather than
left blank) is covered here.

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
from ui.theme_tokens import ITEM_COLOR_MAP, ITEM_DOT_COLOR

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


def cell_keys(by_date: Optional[dict]) -> set:
    """``{iso: {slot_id, …}}`` → ``{"<slot_id>|<iso>", …}``.

    The projections in `ui.formatters` return the first shape and the table
    reads the second. One converter, used by every caller, so the two never
    drift into a set of keys that matches no cell — which renders as a plan
    with nothing pinned and nothing flagged, exactly like a clean one.
    """
    return {f"{slot_id}|{iso}"
            for iso, slots in (by_date or {}).items() for slot_id in (slots or ())}


def warned_cells(diagnostics, plan: Optional[dict] = None) -> set:
    """Cells a WARNING pre-flight diagnostic names, as ``{"<slot>|<iso>"}``.

    Diagnostics address a BASE slot (`rice`), the table addresses the expanded
    one (`rice__2`), so each warning marks every cell of that base slot on that
    day. INFO is skipped: "exactly enough items, no variety" is true of a
    staple by design, and a marker on every staple every day is a marker
    nobody reads.

    A diagnostic with no `date`/`slot` in `affected` addresses the whole solve,
    not a cell — those already have the warnings panel and are dropped here
    rather than being spread over every cell.
    """
    out = set()
    for d in (diagnostics or []):
        if not isinstance(d, dict) or d.get("severity") != "warning":
            continue
        aff = d.get("affected") or {}
        iso, base = aff.get("date"), aff.get("slot")
        if not iso or not base:
            continue
        served = (plan or {}).get(iso) or {}
        out.update(f"{slot_id}|{iso}" for slot_id in served
                   if slot_id.split("__")[0] == base)
    return out


def regen_request(picked: Optional[dict], last_nonce=None) -> Optional[dict]:
    """A component return → ``{iso: [slot_id, …]}``, or None if there is none.

    Two things that have to be right together:

    * A Streamlit component's return value is REPLAYED on every rerun, and
      handling a regenerate ends in `st.rerun()`. Without the nonce check the
      same request comes back on the way in and the table regenerates forever.
      The caller stores the returned `nonce` and passes it back as
      *last_nonce*.
    * The cell key is split back into `(slot_id, iso)` on the SAME `|` the
      table joined them with. Split it the other way round and `/regenerate`
      gets a replace mask keyed by slot, which is a valid-looking dict that
      names no cell the plan has.

    Returns `{"nonce": …, "cells": {iso: [slot_id, …]}}`.
    """
    if not isinstance(picked, dict) or picked.get("action") != "regenerate":
        return None
    nonce = picked.get("nonce")
    if nonce is not None and nonce == last_nonce:
        return None
    by_day: dict = {}
    for cell in (picked.get("cells") or []):
        slot_id, sep, iso = str(cell).partition("|")
        if sep and slot_id and iso:
            by_day.setdefault(iso, []).append(slot_id)
    return {"nonce": nonce, "cells": by_day} if by_day else None


def explain_days(payload: Optional[dict]) -> dict:
    """An `/explain` response → `{iso: {"overview", "checks"}}` for the table.

    The table's per-day panel is the SHORT read: the paragraph a chef actually
    reads, and the verdicts as ticks. The full four-step version — plate,
    pairings, provenance, relaxations, raw bullets — stays in the expander
    below, which is a different reader with a different question.

    Days with no overview and no checks are dropped rather than returned empty,
    because the component only offers a "Why this menu" button for days it has
    something to say about. An empty entry would put a button on screen that
    opens a blank panel, which is what it did before this existed.
    """
    out = {}
    for day in ((payload or {}).get("days") or []):
        iso = str(day.get("date") or "")
        if not iso:
            continue
        checks = [
            {"text": " — ".join(p for p in (
                str(c.get("name", "")).replace("_", " ").strip(),
                str(c.get("detail", "")).strip()) if p),
             "passed": c.get("passed") is not False}
            for c in (day.get("checks") or [])
        ]
        overview = str(day.get("overview") or "").strip()
        if overview or checks:
            out[iso] = {"overview": overview, "checks": checks}
    return out


def day_cells(plan: dict, dates: List[str], day_types: dict,
              nonveg: Optional[dict] = None,
              off_days: Optional[set] = None,
              pinned: Optional[set] = None,
              warned: Optional[set] = None,
              modified: Optional[set] = None,
              regions: Optional[dict] = None,
              issues: Optional[set] = None,
              shared: Optional[set] = None) -> dict:
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
    # BASE slots, not expanded ones: `shared_categories` is configured as
    # `dal`, and the counter serves `dal__1` and `dal__2`.
    shared = {str(s).strip() for s in (shared or set()) if str(s).strip()}

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
            col = _color_key(str(raw))
            cells[iso] = {
                "name": format_item_for_ui(str(raw)),
                "color": col,
                # Two colours, for two jobs. `color_dot` is the SWATCH the cell
                # draws beside the dish; `color_fg` is the READABLE version,
                # used where the colour has to carry text — the dish names in
                # the explain paragraph. They differ only for White, and that
                # difference is the whole reason there are two.
                "color_dot": ITEM_DOT_COLOR.get(col, ""),
                "color_fg": ITEM_COLOR_MAP.get(col, ("", "", ""))[2],
                "nonveg": slot_id in (nonveg.get(iso) or set()),
                "pinned": k in pinned,
                "warn": k in warned,
                "modified": k in modified,
                "title": str(raw),
            }
        rows.append({
            "id": slot_id,
            "label": display_label_for_slot_id(slot_id),
            "shared": slot_id.split("__")[0] in shared,
            "cells": cells,
        })
    return {"days": days, "rows": rows}


def menu_table(block: dict, *, title: str, meta: str = "", hint: str = "",
               explain: Optional[dict] = None, meal: str = "",
               reset_token: str = "",
               key: Optional[str] = None) -> Optional[dict]:
    """Render one service's table. Returns the regenerate request, or None.

    The return is `{"action": "regenerate", "cells": ["<slot>|<iso>", …]}` —
    exactly the cells the planner ticked, which is the shape `/regenerate`
    already takes as its replace mask.
    """
    plan = block.get("plan", {})
    args = day_cells(
        plan, block.get("plan_dates", []),
        block.get("day_types", {}), block.get("nonveg"), block.get("off_days"),
        # `pinned` and `modified` arrive in the `{date: {slot}}` shape every
        # projection in `ui.formatters` uses; `cell_keys` is the one place
        # that turns them into the table's key.
        pinned=cell_keys(block.get("pinned")),
        warned=warned_cells(block.get("rule_diagnostics"), plan),
        modified=cell_keys(block.get("modified")),
        regions=block.get("regions"), issues=block.get("issues"),
        shared=block.get("shared_categories"),
    )
    height = _CHROME_PX + _ROW_PX * (len(args["rows"]) + 1)
    return _component(
        title=title, meta=meta, hint=hint, meal=meal,
        days=args["days"], rows=args["rows"],
        explain=explain or {}, reset_token=reset_token,
        default=None, key=key, height=height,
    )
