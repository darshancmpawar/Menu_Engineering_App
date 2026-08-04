"""Shaping a saved plan for display.

Lifted out of `api/app.py`. Turning stored history rows back into something the
planner can render — attaching item colours and the theme of each day — is
presentation logic, not routing, and it is a pure function of the rows plus the
ontology frame.
"""

from __future__ import annotations

import datetime as dt
from typing import Dict

from src.constants import CONST_SLOTS


def _build_item_color_lookup(df) -> Dict[str, str]:
    """Return ``{normalised_item_name: color_initial_letter}``.

    Used by ``saved_plan`` to re-attach a color suffix to history rows.
    ``menu_history.item_base`` is stored without color (the cooldown
    rules are color-agnostic), but the UI's table renderer expects
    ``item(C)``-shaped strings — without this lookup, loaded plans show
    no color pills.

    Falls back gracefully: items not in *df* (admin-renamed, removed,
    legacy entries) round-trip without a color suffix instead of
    crashing.
    """
    from src.preprocessor.column_mapper import _norm_str, _norm_color

    out: Dict[str, str] = {}
    if df is None or 'item' not in df.columns:
        return out
    color_col = 'item_color' if 'item_color' in df.columns else None
    for _, row in df[['item'] + ([color_col] if color_col else [])].iterrows():
        name = _norm_str(row.get('item', ''))
        if not name:
            continue
        if color_col is None:
            out.setdefault(name, '')
            continue
        col = _norm_color(row.get(color_col, 'unknown'))
        if col == 'unknown' or '_' not in col:
            out.setdefault(name, '')
            continue
        # _norm_color returns shapes like "light_red", "medium_green";
        # the UI's display logic uses the last token's first letter
        # (matches src.solver.menu_solver._color_initial).
        base = col.split('_')[-1]
        out.setdefault(name, base[:1].upper() if base else '')
    return out


def _enrich_history_plan(
    saved: Dict[dt.date, Dict[str, str]], df,
) -> Dict[dt.date, Dict[str, str]]:
    """Turn ``{date: {slot: item_base}}`` (history shape) into
    ``{date: {slot: item_with_color}}`` (UI shape) by looking up each
    item's color in the loaded Excel *df* and appending ``(C)``.

    Constant slots (white_rice, papad, pickle, chutney) round-trip as-is
    since they never carried a color suffix in the first place. Items
    that no longer exist in the ontology fall through without a suffix
    — the UI handles missing-color gracefully (no color pill).
    """
    color_lookup = _build_item_color_lookup(df)
    out: Dict[dt.date, Dict[str, str]] = {}
    for d, slots in saved.items():
        day_out: Dict[str, str] = {}
        for slot_id, item_base in slots.items():
            if not item_base:
                continue
            if slot_id in CONST_SLOTS:
                day_out[slot_id] = item_base
                continue
            initial = color_lookup.get(item_base, '')
            day_out[slot_id] = f'{item_base}({initial})' if initial else item_base
        out[d] = day_out
    return out
