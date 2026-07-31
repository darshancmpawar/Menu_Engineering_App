"""
Color-based menu rules.

* :class:`ColorPairingMenuRule` — forbid two given slots from picking
  items of the same color on the same day.
* :class:`WelcomeDrinkColorMenuRule` — forbid consecutive days from
  using the same welcome-drink color.
* :class:`ColorVarietyMenuRule` — the per-city *numbers* for the daily
  colour-variety / same-colour-cap constraints.

Daily colour variety itself is enforced by the built-in
``MenuSolver._add_color_constraints`` (it needs the per-day colour vars the
solver owns) and pre-flagged by ``diagnostics.color_variety_diagnostics``. What
varies by city is how many colours a day needs and how many dishes may look
alike — Bangalore wants 4 distinct with one colour allowed to reach 3, Pune's
rulebook wants 3 distinct and a flat cap of 2 — so those numbers live in the
city ruleset via ``ColorVarietyMenuRule`` instead of being baked into
``SolverConfig``'s defaults.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from ortools.sat.python import cp_model

from ..preprocessor.column_mapper import _norm_color
from .base_menu_rule import (
    BaseMenuRule,
    Diagnostic,
    DiagnoseContext,
    DiagnosticPhase,
    DiagnosticSeverity,
    MenuRuleType,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ColorPairingMenuRule
# ---------------------------------------------------------------------------


class ColorPairingMenuRule(BaseMenuRule):
    """
    Config:
    {
        "type": "color_pairing",
        "name": "starter_main_color_mismatch",
        "course_type_a": "starter",
        "course_type_b": "veg_gravy"
    }
    """

    def __init__(self, rule_config: Dict[str, Any]):
        super().__init__(rule_config)
        self.rule_type = MenuRuleType.COLOR_PAIRING
        self.course_type_a = rule_config.get('course_type_a', '')
        self.course_type_b = rule_config.get('course_type_b', '')

    def validate_config(self) -> bool:
        if not self.course_type_a or not self.course_type_b:
            return False
        if self.course_type_a == self.course_type_b:
            return False
        return True

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        cells = context.get('cells', [])
        dates = context.get('dates', [])
        find_cells = context.get('find_cells_fn')
        cfg = context.get('cfg')

        if not cells or not find_cells or not cfg:
            return

        color_col = cfg.color_col

        for di in range(len(dates)):
            cells_a = find_cells(cells, di, self.course_type_a)
            cells_b = find_cells(cells, di, self.course_type_b)
            if not cells_a or not cells_b:
                continue

            # Group variables by color for each course type
            colors_a: Dict[str, list] = {}
            for c in cells_a:
                for var, row in zip(c.x_vars, c.cand_rows):
                    col = _norm_color(row.get(color_col, 'unknown'))
                    if col != 'unknown':
                        colors_a.setdefault(col, []).append(var)

            colors_b: Dict[str, list] = {}
            for c in cells_b:
                for var, row in zip(c.x_vars, c.cand_rows):
                    col = _norm_color(row.get(color_col, 'unknown'))
                    if col != 'unknown':
                        colors_b.setdefault(col, []).append(var)

            # For each shared color: at most one side can select it
            for color in set(colors_a) & set(colors_b):
                model.Add(sum(colors_a[color]) + sum(colors_b[color]) <= 1)


# ---------------------------------------------------------------------------
# WelcomeDrinkColorMenuRule
# ---------------------------------------------------------------------------


class WelcomeDrinkColorMenuRule(BaseMenuRule):
    """
    Config:
    {
        "type": "welcome_drink_color",
        "name": "welcome_drink_no_repeat_color"
    }
    """

    def __init__(self, rule_config: Dict[str, Any]):
        super().__init__(rule_config)
        self.rule_type = MenuRuleType.WELCOME_DRINK_COLOR

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        dates = context.get('dates', [])
        known_welcome_colors = context.get('known_welcome_colors', [])
        day_welcome_color_vars = context.get('day_welcome_color_vars', {})

        for di in range(len(dates) - 1):
            for col in known_welcome_colors:
                a = day_welcome_color_vars.get((di, col), [])
                b = day_welcome_color_vars.get((di + 1, col), [])
                if a and b:
                    model.Add(sum(a) + sum(b) <= 1)


# ---------------------------------------------------------------------------
# ColorVarietyMenuRule
# ---------------------------------------------------------------------------


class ColorVarietyMenuRule(BaseMenuRule):
    """Per-city numbers for the built-in daily colour constraints.

    Config (every field optional; omitted ones keep the SolverConfig default)::

        {
            "type": "color_variety",
            "name": "colour_three_distinct_max_two_alike",
            "min_distinct_per_day": 3,
            "max_same_color_per_day": 2,
            "max_colors_at_reach": 0
        }

    This rule adds no CP-SAT constraints of its own — ``MenuSolver`` builds the
    colour block from the per-day colour vars it owns. It carries the parameters,
    which ``api._build_solver_config`` reads via :py:meth:`solver_overrides`. The
    allow-list there is what keeps this from being a back door for rewriting
    unrelated solver settings.
    """

    # ruleset field -> SolverConfig field
    _FIELDS = {
        'min_distinct_per_day': 'min_distinct_colors_per_day',
        'min_distinct_per_day_chinese': 'min_distinct_colors_per_day_chinese',
        'min_distinct_per_day_biryani': 'min_distinct_colors_per_day_biryani',
        'max_same_color_per_day': 'max_same_color_per_day',
        'max_same_color_reach': 'max_same_color_reach',
        'max_colors_at_reach': 'max_colors_at_reach',
        'ignore_rice_gravy_color_diff_on_chinese_day':
            'ignore_rice_gravy_color_diff_on_chinese_day',
    }
    _BOOL_FIELDS = {'ignore_rice_gravy_color_diff_on_chinese_day'}

    def __init__(self, rule_config: Dict[str, Any]):
        super().__init__(rule_config)
        self.rule_type = MenuRuleType.COLOR_VARIETY
        self.overrides: Dict[str, Any] = {}
        self._errors: List[str] = []
        for key, target in self._FIELDS.items():
            if key not in rule_config:
                continue
            raw = rule_config[key]
            if key in self._BOOL_FIELDS:
                self.overrides[target] = bool(raw)
                continue
            try:
                value = int(raw)
            except (TypeError, ValueError):
                self._errors.append(f"{key} must be an integer, got {raw!r}")
                continue
            if value < 0:
                self._errors.append(f"{key} must be >= 0, got {value}")
                continue
            self.overrides[target] = value

    def validate_config(self) -> bool:
        return not self.validation_errors()

    def validation_errors(self) -> List[str]:
        errs = list(self._errors)
        if not self.overrides and not errs:
            errs.append(
                "at least one colour parameter is required "
                f"(one of {sorted(self._FIELDS)})"
            )
        soft = self.overrides.get('max_same_color_per_day')
        reach = self.overrides.get('max_same_color_reach')
        if soft is not None and reach is not None and reach < soft:
            errs.append(
                f"max_same_color_reach ({reach}) cannot be below "
                f"max_same_color_per_day ({soft})"
            )
        return errs

    def solver_overrides(self) -> Dict[str, Any]:
        """SolverConfig fields this rule sets. Read by _build_solver_config."""
        return dict(self.overrides)

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        pass  # parameters only; the constraints are built into MenuSolver

    def diagnose(self, ctx: DiagnoseContext) -> List[Diagnostic]:
        """Confirm the numbers actually reaching the solver.

        Cheap, and it closes the gap where a typo'd field name left the city on
        Bangalore's defaults with nothing in the response saying so — the
        colour rules are the ones most often blamed for an INFEASIBLE plan.
        """
        cfg = ctx.cfg
        if cfg is None or not self.overrides:
            return []
        effective = {
            field: getattr(cfg, field, None) for field in self.overrides
        }
        mismatched = {
            f: (want, effective[f])
            for f, want in self.overrides.items() if effective[f] != want
        }
        if mismatched:
            return [Diagnostic(
                rule=self.name, rule_type=self.rule_type.value,
                severity=DiagnosticSeverity.WARNING,
                phase=DiagnosticPhase.APPLY,
                message=(
                    "Colour parameters in the ruleset did not reach the solver: "
                    + ", ".join(
                        f"{f} configured {want}, solver has {got}"
                        for f, (want, got) in sorted(mismatched.items())
                    )
                ),
                suggestion=(
                    "This is a wiring bug, not a config error — the plan is "
                    "running under the default colour numbers."
                ),
                affected={'mismatched': {f: v[0] for f, v in mismatched.items()}},
            )]
        return [Diagnostic(
            rule=self.name, rule_type=self.rule_type.value,
            severity=DiagnosticSeverity.INFO,
            phase=DiagnosticPhase.APPLY,
            message=(
                "Colour parameters for this city: "
                + ", ".join(f"{f}={v}" for f, v in sorted(effective.items()))
            ),
            suggestion="No action needed.",
            affected=dict(effective),
        )]
