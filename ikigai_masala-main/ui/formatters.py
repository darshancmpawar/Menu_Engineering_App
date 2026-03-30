"""
UI formatting utilities for menu plan display.
"""

import re
from typing import Dict, Optional

from src.constants import DISPLAY_SLOT_NAME, CONST_SLOTS, BASE_SLOT_NAMES


# Day-of-week theme labels (Monday=0)
THEME_LABELS = {
    0: "Mix of South + North",
    1: "Chinese / Indo-Chinese",
    2: "Biryani Day",
    3: "South Indian",
    4: "North Indian",
    5: "Weekend Special",
    6: "Weekend Special",
}

# Map color initial -> (full name, CSS color for display)
_COLOR_MAP = {
    'R': ('Red', '#ef4444'),
    'G': ('Green', '#22c55e'),
    'B': ('Brown', '#a16207'),
    'Y': ('Yellow', '#eab308'),
    'W': ('White', '#a1a1aa'),
    'O': ('Orange', '#f97316'),
    'K': ('Black', '#71717a'),
}


# Theme badge colors keyed by theme name: (background, foreground)
THEME_TAG_COLORS = {
    'mix': ('#22543d', '#86efac'),
    'chinese': ('#7c2d12', '#fdba74'),
    'biryani': ('#7f1d1d', '#fca5a5'),
    'south': ('#1e3a5f', '#93c5fd'),
    'north': ('#4c1d95', '#c4b5fd'),
}

# Theme badge colors keyed by weekday index (Mon=0): (bg, fg, label)
WEEKDAY_THEME_BADGES = {
    0: ("#22543d", "#86efac", "Mix"),
    1: ("#7c2d12", "#fdba74", "Chinese"),
    2: ("#7f1d1d", "#fca5a5", "Biryani"),
    3: ("#1e3a5f", "#93c5fd", "South Indian"),
    4: ("#4c1d95", "#c4b5fd", "North Indian"),
}


def theme_label(weekday: int) -> str:
    return THEME_LABELS.get(weekday, "")


def display_label_for_slot_id(slot_id: str) -> str:
    return DISPLAY_SLOT_NAME.get(slot_id, slot_id.replace("_", " ").title())


def prettify_slot_name(name: str) -> str:
    """Convert underscore-separated slot/item names to readable title case.

    Examples:
        'veg_dry' -> 'Veg Dry'
        'nonveg_main' -> 'Nonveg Main'
    """
    if not name:
        return ""
    return name.replace("_", " ").strip().title()


def _prettify_item_name(name: str) -> str:
    """Convert underscore-separated item names to readable title case.

    Examples:
        'veg_fried_rice' -> 'Veg Fried Rice'
        'hydrabad_chicken_biryani' -> 'Hydrabad Chicken Biryani'
        'dal_tadka' -> 'Dal Tadka'
    """
    if not name:
        return ""
    return name.replace("_", " ").strip().title()


def format_item_for_ui(item_str: str) -> str:
    """Format item string for plain-text display (no HTML)."""
    if not item_str:
        return ""
    cleaned = re.sub(r'\s*\([A-Z]\)\s*$', '', item_str)
    return _prettify_item_name(cleaned)


def format_item_html(item_str: str) -> str:
    """Format item string as HTML with colored color tag.

    Input:  'veg_fried_rice(Y)'
    Output: 'Veg Fried Rice <span style="color:#eab308;">(Yellow)</span>'
    """
    if not item_str:
        return ""
    m = re.search(r'\(([A-Z])\)\s*$', item_str)
    cleaned = re.sub(r'\s*\([A-Z]\)\s*$', '', item_str)
    name = _prettify_item_name(cleaned)

    if m:
        initial = m.group(1)
        color_name, css_color = _COLOR_MAP.get(initial, (initial, '#a1a1aa'))
        return (f'{name} <span style="color:{css_color};font-weight:600;'
                f'font-size:0.75em;">({color_name})</span>')
    return name


def pretty_text(item_str: str) -> str:
    if not item_str:
        return ""
    cleaned = re.sub(r'\s*\([A-Z]\)\s*$', '', item_str)
    return cleaned.strip().title()


def color_suffix(item_str: str) -> Optional[str]:
    m = re.search(r'\(([A-Z])\)\s*$', item_str)
    return m.group(1) if m else None


def slot_sort_key(slot_id: str) -> int:
    """Return sort index for display ordering."""
    base = slot_id.split("__")[0] if "__" in slot_id else slot_id
    try:
        return BASE_SLOT_NAMES.index(base)
    except ValueError:
        return 999
