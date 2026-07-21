"""
Shared utility functions for the solver package.

These helpers are used by menu_solver, solution_formatter, and regenerator.
"""

import datetime as dt
import re
from typing import Dict, Optional


def weekday_type(d: dt.date) -> str:
    """Return the theme type for a given date's weekday."""
    wd = d.strftime('%A').lower()
    return {
        'monday': 'mix', 'tuesday': 'chinese', 'wednesday': 'biryani',
        'thursday': 'south', 'friday': 'north',
    }.get(wd, 'holiday' if wd in ('saturday', 'sunday') else 'normal')


def resolve_alternating_theme(theme: str, d: dt.date) -> str:
    """Resolve a weekly-alternating meta-theme to a concrete theme for date *d*.

    ``chinese_continental`` alternates by ISO-week parity: even week → Chinese,
    odd week → Continental. Deterministic (no stored state), so regenerating the
    same week yields the same theme. Any non-alternating theme is returned as-is.
    """
    if theme == 'chinese_continental':
        return 'chinese' if (d.isocalendar()[1] % 2 == 0) else 'continental'
    return theme


def weekday_type_for_config(d: dt.date, theme_map: Optional[Dict[str, str]] = None) -> str:
    """Return the theme type using per-client overrides if provided.

    Weekly-alternating meta-themes are resolved to a concrete theme for *d* so
    everything downstream (pool filters, badges) sees a real theme.
    """
    if theme_map:
        wd = d.strftime('%A').lower()
        if wd in theme_map:
            return resolve_alternating_theme(theme_map[wd], d)
    return weekday_type(d)


def theme_label(day_type: str) -> str:
    """Return a human-readable label for a day theme type."""
    return {
        'mix': 'Mix of South + North', 'chinese': 'Chinese',
        'biryani': 'Biryani', 'south': 'South Indian',
        'north': 'North Indian', 'continental': 'Continental',
        'chinese_continental': 'Chinese / Continental',
        'holiday': 'Holiday', 'normal': 'Normal',
    }.get(day_type, day_type.capitalize())


def strip_color_suffix(s: str) -> str:
    """Remove trailing color suffix like '(R)' from an item string."""
    return re.sub(r'\([A-Z]\)\s*$', '', (s or '').strip()).strip()


def items_from_day(day_data) -> Dict[str, str]:
    """Extract ``{slot_id: item_str}`` from a day payload.

    Accepts either the rich solution format
        ``{'theme': ..., 'day_type': ..., 'items': {slot: {item, item_base, ...}}}``
    or a flat legacy format
        ``{slot: item_str}``
    and returns ``{slot: item_str}`` in both cases.
    """
    if isinstance(day_data, dict) and 'items' in day_data:
        source = day_data['items']
    else:
        source = day_data or {}
    out: Dict[str, str] = {}
    for slot_id, val in source.items():
        if isinstance(val, dict):
            out[slot_id] = val.get('item', val.get('item_base', ''))
        else:
            out[slot_id] = str(val)
    return out
