"""
Solution formatter for presenting menu plans.

Handles slot-based output format with color suffixes and constant items.
"""

import datetime as dt
from typing import Dict, Any, List, Optional, Set

from ._helpers import (
    weekday_type_for_config as _weekday_type_cfg,
    theme_label as _theme_label,
    strip_color_suffix as _strip_color_suffix,
)
from src.constants import DISPLAY_SLOT_NAME, NONVEG_SLOT
from ..preprocessor.pool_builder import _base_slot, _slot_num


def _display_slot(slot_id: str) -> str:
    base = _base_slot(slot_id)
    num = _slot_num(slot_id)
    base_disp = DISPLAY_SLOT_NAME.get(base, base.replace('_', ' ').title())
    return base_disp if num is None else f'{base_disp} {num}'


class SolutionFormatter:
    """
    Formats cell-based menu planning solutions for output.

    Expects week_plan = {date: {slot_id: item_string_with_color}}
    """

    def __init__(self, week_plan: Dict[dt.date, Dict[str, str]], dates: List[dt.date],
                 theme_map: Optional[Dict[str, str]] = None,
                 nonveg_items: Optional[Set[str]] = None):
        self.week_plan = week_plan
        self.dates = dates
        self._theme_map = theme_map
        # Lower-cased item base-names that are non-vegetarian, used to tag each
        # item with ``is_nonveg`` so the UI / export can colour them. ``None``
        # means "unknown" → everything reported as veg.
        self._nonveg_items = nonveg_items or set()

    def _is_nonveg(self, item_base: str, slot_id: str = '') -> bool:
        """Is this dish non-vegetarian?

        Three-step, in order of confidence:

        1. Exact ontology match (the normal solved-item path).
        2. Whitespace-normalised match, so a hand-written client constant like
           ``"boiled egg"`` still finds ``boiled_egg`` in the snake_case
           ontology.
        3. Slot identity: anything occupying ``nonveg_main`` is non-veg by
           definition. Pinned ``constant_items`` values are free text with no
           ontology row, so without this a constant such as ``"boiled egg"``
           rendered black in the table and the Excel export — a dietary error,
           not a cosmetic one.
        """
        if not item_base:
            return False
        name = item_base.strip().lower()
        if name in self._nonveg_items:
            return True
        if name.replace(' ', '_') in self._nonveg_items:
            return True
        return _base_slot(slot_id) == NONVEG_SLOT if slot_id else False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        result = {}
        for d in self.dates:
            day_key = d.isoformat()
            day_type = _weekday_type_cfg(d, self._theme_map)
            result[day_key] = {
                'theme': _theme_label(day_type),
                'day_type': day_type,
                'items': {},
            }
            for slot_id, item_str in self.week_plan.get(d, {}).items():
                item_base = _strip_color_suffix(item_str)
                result[day_key]['items'][slot_id] = {
                    'display_name': _display_slot(slot_id),
                    'item': item_str,
                    'item_base': item_base,
                    'is_nonveg': self._is_nonveg(item_base, slot_id),
                }
        return result
