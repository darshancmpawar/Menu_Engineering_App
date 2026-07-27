"""
Coupling menu rule: the deep-fried rice / bread / veg-dry family (rulebook
34-42).

  * Liquid rice ⇒ a deep-fried Veg Dry or Starter must be present, scoped to
    whichever of those slots is active (34-36).
  * Deep-fried Veg Dry ⇒ rice-bread AND liquid rice (37).
  * Rice-bread ⇒ liquid rice (38).
  * A dosa-type bread with an active Non-Veg Main ⇒ the non-veg is a
    South-Indian chicken gravy (41, guarded on availability).
  * Weekly: rice-bread on ≤1 day (62), deep-fried Veg Dry on ≤1 day (39).

Rulebook §5 retires the old "rice-bread always needs a deep-fried Starter"
coupling, so that link is intentionally absent.
"""

from typing import Dict, Any, List
from ortools.sat.python import cp_model
from .base_menu_rule import (
    BaseMenuRule,
    Diagnostic,
    DiagnosticPhase,
    DiagnosticSeverity,
    DiagnoseContext,
    MenuRuleType,
)


class CouplingMenuRule(BaseMenuRule):
    """
    Config:
    {
        "type": "coupling",
        "name": "deep_fried_coupling"
    }
    """

    def __init__(self, rule_config: Dict[str, Any]):
        super().__init__(rule_config)
        self.rule_type = MenuRuleType.COUPLING

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        cells = context.get('cells', [])
        dates = context.get('dates', [])
        find_cells = context.get('find_cells_fn')
        link_any = context.get('link_any_fn')

        if not cells or not find_cells or not link_any:
            return

        bread_rb_day: List = []
        vegdry_df_day: List = []

        def _detect(cell_list, pred, name):
            """OR bool over items in `cell_list` matching `pred`; forced 0 when
            the slot is inactive (empty cell_list)."""
            y = model.NewBoolVar(name)
            lits = [
                v for c in (cell_list or [])
                for v, r in zip(c.x_vars, c.cand_rows) if pred(r)
            ]
            link_any(model, lits, y)  # link_any([], y) sets y == 0
            return y, lits

        for di in range(len(dates)):
            rice_cells = find_cells(cells, di, 'rice')
            if not rice_cells:
                continue  # no rice slot → the whole coupling family is moot
            bread_cells = find_cells(cells, di, 'bread')
            starter_cells = find_cells(cells, di, 'starter')
            vegdry_cells = find_cells(cells, di, 'veg_dry')
            nonveg_cells = find_cells(cells, di, 'nonveg_main')

            rice_liq, rice_liq_lits = _detect(
                rice_cells, lambda r: int(r.get('is_liquid_rice', 0) or 0) == 1,
                f'rice_liquid_{di}')
            bread_rb, _ = _detect(
                bread_cells, lambda r: int(r.get('is_rice_bread', 0) or 0) == 1,
                f'bread_ricebread_{di}')
            starter_df, _ = _detect(
                starter_cells, lambda r: int(r.get('is_deep_fried_starter', 0) or 0) == 1,
                f'starter_deepfried_{di}')
            vegdry_any, _ = _detect(
                vegdry_cells, lambda r: int(r.get('is_deep_fried_veg_dry', 0) or 0) == 1,
                f'vegdry_any_deepfried_{di}')
            bread_rb_day.append(bread_rb)
            vegdry_df_day.append(vegdry_any)

            # Rules 34-36: liquid rice requires at least one deep-fried item
            # among the *active* Veg Dry / Starter slots. If both are inactive
            # this forces rice_liq == 0 (rule 36); if only one is active that
            # one must carry it (rule 35).
            model.Add(vegdry_any + starter_df >= rice_liq)
            # Rule 37: deep-fried Veg Dry ⇒ rice-bread AND liquid rice.
            model.Add(vegdry_any <= rice_liq)
            model.Add(vegdry_any <= bread_rb)
            # Rule 38: rice-bread ⇒ liquid rice.
            model.Add(bread_rb <= rice_liq)
            # (Rulebook §5 retires the old rice-bread ⇔ deep-fried-starter
            # coupling, so it is intentionally not added here.)

            # Rule 41: a dosa-type bread with an active Non-Veg Main forces the
            # non-veg to a South-Indian chicken gravy. Guarded on availability
            # (only when the day actually has an SI-chicken candidate) so it can
            # never make the model INFEASIBLE — a missing candidate is a data
            # gap for the diagnostics to surface, not a hard failure.
            if bread_cells and nonveg_cells:
                dosa_lits = [
                    v for c in bread_cells
                    for v, r in zip(c.x_vars, c.cand_rows)
                    if int(r.get('is_dosa', 0) or 0) == 1
                    or int(r.get('is_dosa_family', 0) or 0) == 1
                ]
                nv = [
                    (v, int(r.get('is_south_chicken_gravy', 0) or 0) == 1)
                    for c in nonveg_cells for v, r in zip(c.x_vars, c.cand_rows)
                ]
                if dosa_lits and any(is_si for _, is_si in nv):
                    dosa_bread = model.NewBoolVar(f'bread_dosa_{di}')
                    link_any(model, dosa_lits, dosa_bread)
                    for v, is_si in nv:
                        if not is_si:
                            model.Add(v + dosa_bread <= 1)

        # Weekly limits: rice-bread on <= 1 day (rule 62), deep-fried Veg Dry
        # on <= 1 day (rule 39).
        if bread_rb_day:
            model.Add(sum(bread_rb_day) <= 1)
        if vegdry_df_day:
            model.Add(sum(vegdry_df_day) <= 1)

    def diagnose(self, ctx: DiagnoseContext) -> List[Diagnostic]:
        """Coupling constraints are upper bounds (rice-bread ⇒ liquid
        rice, etc.) so they rarely cause hard infeasibility on their
        own. The diagnostic value here is calling out **asymmetric
        data**: a client whose bread pool has rice-bread items but
        whose rice pool has NO liquid-rice items will silently never
        pick those rice-breads — and the user's intent ("I added these
        rice-breads so they'd appear") is lost.

        Emits WARNING per asymmetric pair so the user can either add
        the missing pair or remove the orphaned data.
        """
        diags: List[Diagnostic] = []
        bread = ctx.pools.get('bread')
        rice = ctx.pools.get('rice')

        def _flag_count(pool, col):
            if pool is None or col not in pool.columns:
                return None
            return int(pool[col].fillna(0).astype(int).eq(1).sum())

        rb = _flag_count(bread, 'is_rice_bread')
        liquid = _flag_count(rice, 'is_liquid_rice')

        if rb and liquid == 0:
            diags.append(Diagnostic(
                rule=self.name, rule_type=self.rule_type.value,
                severity=DiagnosticSeverity.WARNING,
                phase=DiagnosticPhase.APPLY,
                message=(
                    f"Bread pool has {rb} rice-bread item"
                    f"{'s' if rb != 1 else ''} but rice pool has 0 "
                    f"liquid-rice items. The coupling constraint "
                    f"forbids picking rice-bread without liquid rice, "
                    f"so those rice-breads will never be selected."
                ),
                suggestion=(
                    "Add at least one liquid-rice item (is_liquid_rice=1) "
                    "to the rice pool, or remove the rice-bread items if "
                    "the asymmetry is intentional."
                ),
                affected={
                    'is_rice_bread_count': rb,
                    'is_liquid_rice_count': liquid,
                },
            ))
        return diags
