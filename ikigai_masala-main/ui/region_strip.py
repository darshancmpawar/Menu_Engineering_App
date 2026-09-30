"""The regional-days strip as an interactive Streamlit component.

`st.selectbox` can hold a day's region options but not the REASONS the other
regions are missing from it, and a region silently absent from a list reads as
forgotten — the operator cannot tell "Rajasthan was weighed and this city has
three slots of it" from a broken list. The menu here shows every region, the
ones that fit above the ones that do not, each rejection carrying its reason.

`region_day_args` is the pure shaping — plain data in, plain data out, no
Streamlit — so the grouping and the chip states are testable without a browser
or a solver. See `ui/region_strip/index.html` for the component itself.

Picking a region posts back, the same as the selectbox it replaces, because
what is picked is state Python owns: `_render_region_strip` returns it and the
generate path reads it. Only OPENING a menu is local, which is the part that
would otherwise cost a rerun per click.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Dict, List, Optional

import streamlit.components.v1 as components

_DIR = Path(__file__).parent / "region_strip"
_component = components.declare_component("ikigai_region_strip", path=str(_DIR))

#: Enough of the thin list to show it was measured, before it becomes a wall.
_THIN_SHOWN = 4


def _label(iso: str, fmt: str) -> str:
    try:
        return dt.date.fromisoformat(iso).strftime(fmt)
    except ValueError:
        return iso


def region_day_args(meta: dict, dates: List[str], day_themes: dict,
                    applied: Optional[dict] = None,
                    problems: Optional[list] = None,
                    city: str = "") -> List[dict]:
    """One entry per day: the chip's state and the whole menu behind it.

    Three groups, in the order the menu prints them — the regions this day CAN
    take, the ones its theme excludes, and the ones the city is too thin for.
    The last two are shown greyed rather than dropped, each with its reason.

    A day whose theme admits NO region is disabled rather than given an empty
    menu: a `chinese` or `biryani` day narrows its mains by flag, not by
    cuisine, so a region's dishes are gone before any floor could be read.
    """
    applied = applied or {}
    bad_days = {str(p.get("date")) for p in (problems or [])
                if isinstance(p, dict) and p.get("date")}
    regions = meta.get("regions") or []
    compat_all = meta.get("theme_compatibility") or {}

    out = []
    for iso in dates:
        theme = str((day_themes or {}).get(iso, "") or "").strip().lower()
        theme_name = theme.replace("_", " ").title() if theme else "No theme"
        compat = set(compat_all.get(theme, []))

        ok, wrong, thin = [], [], []
        for r in regions:
            name = str(r.get("name", ""))
            slots = len(r.get("deep_slots") or [])
            if not r.get("themeable"):
                thin.append(name)
            elif name in compat:
                ok.append({"value": name, "name": name,
                           "meta": f"{slots} slots"})
            else:
                fams = "/".join(sorted(r.get("cuisine_families") or [])) or "regional"
                wrong.append({"name": name, "meta": fams.replace("_", " ").title()})

        picked = str(applied.get(iso, "") or "")
        more = len(thin) - _THIN_SHOWN
        out.append({
            "iso": iso,
            "chip": f"{_label(iso, '%a')} · {theme_name}".upper(),
            "long": _label(iso, "%A %d %b"),
            "applied": picked,
            "below_floor": iso in bad_days,
            "disabled": not ok,
            "title": (f"A {theme_name} day narrows its main dishes to "
                      f"{theme_name} food, so no region fits." if not ok else ""),
            "menu_title": f"{_label(iso, '%A')} · {theme_name} day",
            "menu_sub": ("Every region fits this day."
                         if len(ok) == len(regions) else "Regions that fit this day"),
            # "No region" is an OPTION, not the absence of one: picking it back
            # is how a day is cleared, and a menu you can only add from is a
            # menu you cannot undo.
            "options": [{"value": "", "name": "No region", "meta": "theme only"}] + ok,
            "wrong": wrong,
            "wrong_label": f"Not for a {theme_name} day" if wrong else "",
            "thin_label": f"Too few dishes in {city}:" if city else "Too few dishes here:",
            "thin": (", ".join(thin[:_THIN_SHOWN])
                     + (f" and {more} more" if more > 0 else "")) if thin else "",
        })
    return out


def region_strip(days: List[dict], *, picks: Dict[str, str],
                 apply_enabled: bool = False, reset_enabled: bool = False,
                 save_enabled: bool = False, apply_label: str = "Apply to menu",
                 save_label: str = "Save as weekly default",
                 save_title: str = "", info: str = "",
                 title: str = "Regional days",
                 sub: str = "On top of the day's theme",
                 reset_token: str = "", key: Optional[str] = None):
    """Render the strip. Returns the request, or None.

    `{"action": "pick"|"apply"|"reset"|"save", "picks": {iso: region}}`.
    """
    # The chips are one row; an open menu is 280px wide and as tall as its
    # region list, and the component measures and reports that itself.
    return _component(
        header={"title": title, "sub": sub},
        days=days, picks=picks,
        actions={"apply": apply_enabled, "reset": reset_enabled,
                 "save": save_enabled, "apply_label": apply_label,
                 "save_label": save_label, "save_title": save_title},
        info=info, reset_token=reset_token,
        default=None, key=key, height=96,
    )
