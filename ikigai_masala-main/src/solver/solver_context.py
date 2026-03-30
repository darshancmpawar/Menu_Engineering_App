"""
Typed context object passed to menu rules during solver execution.

Replaces the untyped Dict[str, Any] context with a proper dataclass.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple, Callable, Any, TYPE_CHECKING

from ortools.sat.python import cp_model

if TYPE_CHECKING:
    from .menu_solver import SolverConfig, _Cell


@dataclass
class SolverContext:
    """Typed context passed to rule.apply() and rule.get_objective_terms()."""

    cells: List[_Cell]
    dates: List[dt.date]
    day_types: List[str]
    item_to_vars: Dict[str, List[cp_model.IntVar]]
    day_color_vars: Dict[Tuple[int, str], List[cp_model.IntVar]]
    day_rice_color_vars: Dict[Tuple[int, str], List[cp_model.IntVar]]
    day_gravy_color_vars: Dict[Tuple[int, str], List[cp_model.IntVar]]
    day_premium_vars: Dict[int, List[cp_model.IntVar]]
    day_welcome_color_vars: Dict[Tuple[int, str], List[cp_model.IntVar]]
    monday_south_lits: List[cp_model.IntVar]
    monday_north_lits: List[cp_model.IntVar]
    theme_fallback_bools: List[cp_model.IntVar]
    known_colors: List[str]
    known_welcome_colors: List[str]
    cfg: SolverConfig
    recent_sigs: Set[str]
    find_cells_fn: Callable
    link_any_fn: Callable

    def as_dict(self) -> Dict[str, Any]:
        """Convert to dict for backward compatibility with existing rules."""
        return {
            'cells': self.cells,
            'dates': self.dates,
            'day_types': self.day_types,
            'item_to_vars': self.item_to_vars,
            'day_color_vars': self.day_color_vars,
            'day_rice_color_vars': self.day_rice_color_vars,
            'day_gravy_color_vars': self.day_gravy_color_vars,
            'day_premium_vars': self.day_premium_vars,
            'day_welcome_color_vars': self.day_welcome_color_vars,
            'monday_south_lits': self.monday_south_lits,
            'monday_north_lits': self.monday_north_lits,
            'theme_fallback_bools': self.theme_fallback_bools,
            'known_colors': self.known_colors,
            'known_welcome_colors': self.known_welcome_colors,
            'cfg': self.cfg,
            'recent_sigs': self.recent_sigs,
            'find_cells_fn': self.find_cells_fn,
            'link_any_fn': self.link_any_fn,
        }
