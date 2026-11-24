"""
Menu rule definitions and handlers for menu planning.
"""

from .base_menu_rule import (
    BaseMenuRule,
    MenuRuleType,
    MenuRuleSeverity,
    Diagnostic,
    DiagnosticSeverity,
    DiagnosticPhase,
    DiagnoseContext,
)
from .diagnostics import (
    run_diagnostics,
    summarize,
    has_blocking_errors,
    pool_warnings_projection,
)
from .unique_items_menu_rule import UniqueItemsMenuRule
from .coupling_menu_rule import CouplingMenuRule
from .curd_side_menu_rule import CurdSideMenuRule

# Consolidated domain modules
from .theme_rules import (
    ThemeDayMenuRule,
    ThemeSlotFilterRule,
    ThemeStarterPreferenceRule,
    ThemeFallbackPenaltyRule,
)
from .color_rules import (
    ColorPairingMenuRule,
    WelcomeDrinkColorMenuRule,
)
from .cooldown_rules import (
    ItemCooldownMenuRule,
    RiceBreadGapMenuRule,
    WeekSignatureCooldownMenuRule,
)
from .nonveg_rules import (
    NonvegBiryaniWeeklyRule,
)

# Per-client rules
from .ingredient_ban_rule import IngredientBanRule
from .seasonal_ban_rule import SeasonalBanRule
from .slot_day_restriction_rule import SlotDayRestrictionRule

from .menu_rule_loader import MenuRuleLoader

__all__ = [
    'BaseMenuRule', 'MenuRuleType', 'MenuRuleSeverity', 'MenuRuleLoader',
    # diagnostics
    'Diagnostic', 'DiagnosticSeverity', 'DiagnosticPhase', 'DiagnoseContext',
    'run_diagnostics', 'summarize', 'has_blocking_errors',
    'pool_warnings_projection',
    'UniqueItemsMenuRule', 'CouplingMenuRule', 'CurdSideMenuRule',
    # theme
    'ThemeDayMenuRule', 'ThemeSlotFilterRule',
    'ThemeStarterPreferenceRule', 'ThemeFallbackPenaltyRule',
    # color
    'ColorPairingMenuRule', 'WelcomeDrinkColorMenuRule',
    # cooldown
    'ItemCooldownMenuRule', 'RiceBreadGapMenuRule',
    'WeekSignatureCooldownMenuRule',
    # nonveg
    'NonvegBiryaniWeeklyRule',
    # per-client
    'IngredientBanRule', 'SeasonalBanRule', 'SlotDayRestrictionRule',
]
