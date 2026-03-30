"""
Base menu rule class for all rule types.

Rules participate in two phases:
1. **Pre-filter phase** — ``pre_filter_pool()`` is called during candidate pool
   building (before CP-SAT variables exist).  Rules that need to remove items
   from a slot's candidate pool override this method.
2. **CP-SAT phase** — ``apply()`` adds hard constraints and
   ``get_objective_terms()`` contributes soft-constraint terms to the objective.
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict, Any, List

import datetime as dt
import pandas as pd
from ortools.sat.python import cp_model


class MenuRuleType(Enum):
    """Types of menu rules supported."""
    # Original MVP rules
    CUISINE = "cuisine"
    COLOR_PAIRING = "color_pairing"
    COLOR_VARIETY = "color_variety"
    UNIQUE_ITEMS = "unique_items"
    # Theme system
    THEME_DAY = "theme_day"
    # Hard constraints
    COUPLING = "coupling"
    CURD_SIDE = "curd_side"
    PREMIUM = "premium"
    WELCOME_DRINK_COLOR = "welcome_drink_color"
    # Cooldown / pre-filter rules
    ITEM_COOLDOWN = "item_cooldown"
    RICEBREAD_GAP = "ricebread_gap"
    WEEK_SIGNATURE_COOLDOWN = "week_signature_cooldown"
    THEME_SLOT_FILTER = "theme_slot_filter"
    NONVEG_DRY_PREFERENCE = "nonveg_dry_preference"
    # Soft constraints
    THEME_STARTER_PREFERENCE = "theme_starter_preference"
    THEME_FALLBACK_PENALTY = "theme_fallback_penalty"


class BaseMenuRule(ABC):
    """
    Abstract base class for all menu rules.
    All rule types must inherit from this class.
    """

    def __init__(self, rule_config: Dict[str, Any]):
        self.config = rule_config
        self.rule_type = None
        self.enabled = True
        self.name = rule_config.get('name', 'unnamed_rule')
        self.priority = rule_config.get('priority', 1)

    @abstractmethod
    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        """
        Apply the menu rule to the CP-SAT model.

        Args:
            model: OR-Tools CP-SAT model
            variables: Dictionary of decision variables
            menu_data: Menu data (DataFrame or dict)
            context: Additional context including 'cells', 'day_types', etc.
        """
        pass

    @abstractmethod
    def validate_config(self) -> bool:
        """Validate the menu rule configuration."""
        pass

    def pre_filter_pool(self, pool: pd.DataFrame, date: dt.date,
                        base_slot: str, day_type: str,
                        filter_context: Dict[str, Any]) -> pd.DataFrame:
        """Filter candidate pool before cell building.

        Called once per (date, base_slot) during pool construction.
        Override in subclasses that need to remove items from candidate pools.

        Args:
            pool: DataFrame of candidate items for this slot.
            date: The planning date.
            base_slot: Base slot name (e.g. 'rice', 'starter').
            day_type: Theme type ('mix', 'chinese', 'biryani', 'south', 'north', …).
            filter_context: Runtime data including 'cfg', 'banned_by_date',
                            'ricebread_ban_day', 'pools' (full unfiltered pools).

        Returns:
            Filtered DataFrame (may be the same object if no filtering needed).
        """
        return pool

    def get_objective_terms(self, model: cp_model.CpModel,
                           context: Dict[str, Any]) -> List:
        """
        Return objective function terms contributed by this rule.

        Override in subclasses for soft constraints.
        Default: returns empty list (no contribution to objective).
        """
        return []

    def get_description(self) -> str:
        return f"{self.rule_type.value}: {self.name}"

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name='{self.name}', enabled={self.enabled})>"
