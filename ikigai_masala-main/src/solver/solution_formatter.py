"""
Solution formatter for presenting menu plans.

Handles slot-based output format with color suffixes and constant items.
"""

import datetime as dt
import logging
from typing import Dict, Any, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

from ._helpers import (
    weekday_type_for_config as _weekday_type_cfg,
    theme_label as _theme_label,
    strip_color_suffix as _strip_color_suffix,
)
from src.constants import DISPLAY_SLOT_NAME, CONST_SLOTS
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
                 theme_map: Optional[Dict[str, str]] = None):
        self.week_plan = week_plan
        self.dates = dates
        self._theme_map = theme_map

    def print_summary(self) -> None:
        print("\n" + "=" * 60)
        print("MENU PLAN SOLUTION")
        print("=" * 60)
        print(f"\nGenerated menu for {len(self.dates)} days")
        for d in self.dates:
            day_type = _weekday_type_cfg(d, self._theme_map)
            items = self.week_plan.get(d, {})
            slot_count = len([s for s in items if s not in CONST_SLOTS])
            print(f"  {d.isoformat()} ({_theme_label(day_type)}): {slot_count} items")
        print("=" * 60)

    def _build_export_dataframe(self) -> pd.DataFrame:
        """Build the shared DataFrame used by both CSV and Excel export."""
        slot_order = []
        for d in self.dates:
            day_map = self.week_plan.get(d, {})
            if day_map:
                slot_order = list(day_map.keys())
                break

        cols = [
            f"{_theme_label(_weekday_type_cfg(d, self._theme_map))}-{d.strftime('%A')}({d.isoformat()})"
            for d in self.dates
        ]

        rows = []
        for slot_id in slot_order:
            row = {'Slot': _display_slot(slot_id)}
            for d, col_name in zip(self.dates, cols):
                row[col_name] = self.week_plan.get(d, {}).get(slot_id, '')
            rows.append(row)

        return pd.DataFrame(rows)

    def to_csv(self, output_path: str) -> None:
        """Export to CSV: rows=slots, columns=dates with theme headers."""
        if not self.dates:
            return
        df = self._build_export_dataframe()
        df.to_csv(output_path, index=False)
        logger.info("Exported menu plan to %s", output_path)

    def to_excel(self, output_path: str) -> None:
        """Export to Excel: same format as CSV."""
        if not self.dates:
            return
        df = self._build_export_dataframe()
        df.to_excel(output_path, index=False)
        logger.info("Exported menu plan to %s", output_path)

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
                result[day_key]['items'][slot_id] = {
                    'display_name': _display_slot(slot_id),
                    'item': item_str,
                    'item_base': _strip_color_suffix(item_str),
                }
        return result
