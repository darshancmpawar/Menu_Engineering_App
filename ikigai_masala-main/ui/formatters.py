"""
UI formatting utilities for menu plan display.
"""

import html
import re
from typing import Any, Dict, Set, Tuple

from src.constants import DISPLAY_SLOT_NAME, BASE_SLOT_NAMES, DISPLAY_SLOT_ORDER  # noqa: F401
from ui.theme_tokens import ITEM_COLOR_MAP, PULSE_THEME_COLORS


# Map color initial -> (full name, CSS bg color, CSS text color).
# Sourced from the shared Pulse palette (light tints).
_COLOR_MAP: Dict[str, Tuple[str, str, str]] = ITEM_COLOR_MAP


# Theme badge colors keyed by theme name: (background, foreground).
# Shared with the customisation editor via the Pulse palette.
THEME_TAG_COLORS = PULSE_THEME_COLORS

THEME_ICONS = {
    'mix':     '&#9670;',   # diamond
    'chinese': '&#9672;',   # circle
    'biryani': '&#9733;',   # star
    'south':   '&#9650;',   # triangle up
    'north':   '&#9632;',   # square
    'continental': '&#9873;',        # flag
    'chinese_continental': '&#8646;',  # left-right arrows (alternates)
}


def display_label_for_slot_id(slot_id: str) -> str:
    return DISPLAY_SLOT_NAME.get(slot_id, slot_id.replace("_", " ").title())


def _prettify_item_name(name: str) -> str:
    if not name:
        return ""
    return name.replace("_", " ").strip().title()


def format_item_for_ui(item_str: str) -> str:
    """Format item string for plain-text display (no HTML)."""
    if not item_str:
        return ""
    cleaned = re.sub(r'\s*\([A-Z]\)\s*$', '', item_str)
    return _prettify_item_name(cleaned)


def format_item_html(item_str: str, is_nonveg: bool = False) -> str:
    """Format item string as HTML with colored pill for the color tag.

    Input:  'veg_fried_rice(Y)'
    Output: 'Veg Fried Rice <span class="color-pill" ...>(Yellow)</span>'

    When ``is_nonveg`` is True the item name carries the ``item-nonveg``
    class so it renders red.
    """
    if not item_str:
        return '<span class="cell-empty">&mdash;</span>'
    m = re.search(r'\(([A-Z])\)\s*$', item_str)
    cleaned = re.sub(r'\s*\([A-Z]\)\s*$', '', item_str)
    # Item names originate from the ontology / Supabase, but those are
    # admin-editable, so escape before embedding into st.markdown output
    # that runs with unsafe_allow_html=True.
    name = html.escape(_prettify_item_name(cleaned))
    name_cls = "item-name item-nonveg" if is_nonveg else "item-name"

    if m:
        initial = m.group(1)
        color_name, bg, fg = _COLOR_MAP.get(initial, (initial, '#F0F0F0', '#555555'))
        return (
            f'<span class="{name_cls}">{name}</span>'
            f'<span class="color-pill" style="background:{bg};color:{fg};">'
            f'{html.escape(color_name)}</span>'
        )
    return f'<span class="{name_cls}">{name}</span>'


def nonveg_slots_from_solution(
    raw_solution: Dict[str, Any],
) -> Dict[str, Set[str]]:
    """Return ``{date_iso: {slot_id, …}}`` for slots holding a non-veg dish.

    Reads the ``is_nonveg`` flag the API attaches to each item so both the
    on-screen table and the Excel export can colour non-veg dishes red.
    """
    out: Dict[str, Set[str]] = {}
    for date_key, day_data in raw_solution.items():
        source = day_data.get('items') if isinstance(day_data, dict) and 'items' in day_data else (day_data or {})
        nv = {
            slot_id for slot_id, val in source.items()
            if isinstance(val, dict) and val.get('is_nonveg')
        }
        if nv:
            out[date_key] = nv
    return out


def shared_items_from_solution(
    raw_solution: Dict[str, Any], shared_categories,
) -> list:
    """Pins for a counter's common categories, as ``[[date, slot_id, item], …]``.

    Reads a ``/plan`` solution and returns, for every cell whose base slot is in
    *shared_categories*, the chosen dish's ``item_base``. The planner feeds this
    into the *other* counters' ``/plan`` calls (as ``shared_items``) so a common
    category resolves to the same dish across counters on each day — DXC's
    "common categories are identical across counters".
    """
    bases = {str(c).strip() for c in (shared_categories or []) if str(c).strip()}
    if not bases:
        return []
    out: list = []
    for date_key, day_data in (raw_solution or {}).items():
        items = day_data.get('items') if isinstance(day_data, dict) else None
        if not isinstance(items, dict):
            continue
        for slot_id, meta in items.items():
            base = slot_id.split('__')[0]
            if base not in bases or not isinstance(meta, dict):
                continue
            item_base = meta.get('item_base') or meta.get('item')
            if item_base:
                out.append([date_key, slot_id, str(item_base)])
    return out


def flatten_api_solution(
    raw_solution: Dict[str, Any],
) -> Tuple[Dict[str, Dict[str, str]], Dict[str, str]]:
    """Turn the API's ``/plan`` response body into UI-friendly structures.

    The API returns ``{date_iso: {theme, day_type, items: {slot: {item, ...}}}}``.
    For rendering, the UI only needs ``{date_iso: {slot: item_str}}`` plus
    ``{date_iso: day_type}`` for the column headers.
    """
    flat: Dict[str, Dict[str, str]] = {}
    day_types: Dict[str, str] = {}
    for date_key, day_data in raw_solution.items():
        if isinstance(day_data, dict) and 'items' in day_data:
            day_types[date_key] = day_data.get('day_type', '')
            source = day_data['items']
        else:
            source = day_data or {}
        slots: Dict[str, str] = {}
        for slot_id, val in source.items():
            if isinstance(val, dict):
                slots[slot_id] = val.get('item', val.get('item_base', ''))
            else:
                slots[slot_id] = str(val)
        flat[date_key] = slots
    return flat, day_types


def slot_sort_key(slot_id: str) -> int:
    """Return sort index for display ordering (menu table + Excel export).

    Ranks by the canonical DISPLAY_SLOT_ORDER so constant slots (e.g. white
    rice) interleave with base slots and non-veg sorts last.
    """
    base = slot_id.split("__")[0] if "__" in slot_id else slot_id
    try:
        return DISPLAY_SLOT_ORDER.index(base)
    except ValueError:
        return 999
