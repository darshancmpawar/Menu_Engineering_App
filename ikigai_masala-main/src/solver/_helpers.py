"""
Shared utility functions for the solver package.

These helpers are used by menu_solver, solution_formatter, and regenerator.
"""

import datetime as dt
import re
from typing import Dict, List, Optional, Set, Tuple

from src.constants import DEFAULT_WEEKDAY_THEMES
from ..preprocessor.pool_builder import _base_slot


def cell_is_skipped(
    skip_cells: Set[Tuple[dt.date, str]], d: dt.date, slot_id: str,
) -> bool:
    """Return True if the ``(date, slot_id)`` cell must not be solved.

    ``skip_cells`` deliberately holds two kinds of entry in one set:

    * ``(date, base_slot)`` — every expansion of the base slot is skipped.
      This is what ``slot_day_restriction`` emits, and what a client constant
      that replaces a whole slot family emits.
    * ``(date, slot_id)`` — only that one expansion is skipped, so a client
      constant can pin ``nonveg_main__2`` while ``nonveg_main__1`` is still
      solved normally.

    A base slot with only one expansion *is* its own slot id, so for count-1
    slots the two checks collapse and can never disagree.
    """
    if (d, slot_id) in skip_cells:
        return True
    return (d, _base_slot(slot_id)) in skip_cells


_WEEKDAY_NAMES = (
    'monday', 'tuesday', 'wednesday', 'thursday',
    'friday', 'saturday', 'sunday',
)


def weekday_name(d: dt.date) -> str:
    """Return the lowercase English weekday name for *d*.

    Indexes a fixed tuple rather than calling ``strftime('%A').lower()``:
    ``%A`` is locale-dependent, so under a non-English locale every
    weekday comparison in the codebase (theme maps, working days,
    per-weekday constants) silently stops matching and the menu quietly
    loses its themes.
    """
    return _WEEKDAY_NAMES[d.weekday()]


def planned_dates(cfg) -> List[dt.date]:
    """Resolve the horizon a :class:`SolverConfig` actually plans.

    ``explicit_dates`` (set by the API, already weekend-aware) wins over
    the ``start_date`` + ``days`` range, and a client-level
    ``working_days`` restriction filters whatever remains.

    Both :meth:`MenuSolver.solve` and :meth:`MenuRegenerator.regenerate`
    call this. They used to derive the horizon independently — the
    regenerator built a plain contiguous ``start_date + i`` range — so on
    any non-Monday start, any weekend-skipping client, or any client with
    ``working_days`` the two lists diverged. The regenerator then locked
    dates the plan never contained and left real cells unlocked, silently
    re-solving menu entries the user had not selected.
    """
    if getattr(cfg, 'explicit_dates', None):
        dates = list(cfg.explicit_dates)
    else:
        dates = [
            cfg.start_date + dt.timedelta(days=i) for i in range(cfg.days)
        ]
    working = getattr(cfg, 'working_days', None)
    if working:
        allowed = {str(w).strip().lower() for w in working}
        dates = [d for d in dates if weekday_name(d) in allowed]
    return dates


def weekday_type(d: dt.date) -> str:
    """Return the theme type for a given date's weekday."""
    wd = weekday_name(d)
    return DEFAULT_WEEKDAY_THEMES.get(
        wd, 'holiday' if wd in ('saturday', 'sunday') else 'normal')


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
        wd = weekday_name(d)
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
