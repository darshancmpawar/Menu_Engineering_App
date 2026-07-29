"""
Curd-side menu rule: biryani -> raita, pulao -> raita, else -> curd.
"""

from typing import Dict, Any, List, Set
from ortools.sat.python import cp_model
from .base_menu_rule import (
    BaseMenuRule,
    Diagnostic,
    DiagnoseContext,
    DiagnosticPhase,
    DiagnosticSeverity,
    MenuRuleType,
)
from ..preprocessor.column_mapper import _norm_str
from src.constants import PULAO_SUBCATS


class CurdSideMenuRule(BaseMenuRule):
    """
    Config:
    {
        "type": "curd_side",
        "name": "curd_raita_logic",
        "pulao_subcats": ["south_veg_pulao", "north_simple_veg_pulao", ...]
    }
    """

    def __init__(self, rule_config: Dict[str, Any]):
        super().__init__(rule_config)
        self.rule_type = MenuRuleType.CURD_SIDE
        self.pulao_subcats: Set[str] = set(rule_config.get('pulao_subcats', PULAO_SUBCATS))

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        cells = context.get('cells', [])
        dates = context.get('dates', [])
        day_types = context.get('day_types', [])
        find_cells = context.get('find_cells_fn')
        link_any = context.get('link_any_fn')

        if not cells or not find_cells or not link_any:
            return

        for di, _ in enumerate(dates):
            day_type = day_types[di] if di < len(day_types) else 'normal'
            rice_cells = find_cells(cells, di, 'rice')
            curd_cells = find_cells(cells, di, 'curd_side')

            if not rice_cells or not curd_cells:
                continue

            # Pulao detection in rice
            rice_pulao_lits = [
                v for rc in rice_cells
                for v, row in zip(rc.x_vars, rc.cand_rows)
                if _norm_str(row.get('sub_category', '')) in self.pulao_subcats
            ]
            rice_is_pulao = model.NewBoolVar(f'rice_is_pulao_{di}')
            link_any(model, rice_pulao_lits, rice_is_pulao)

            # Curd vs raita detection
            curd_lits, raita_lits = [], []
            for cc in curd_cells:
                for v, row in zip(cc.x_vars, cc.cand_rows):
                    sc = _norm_str(row.get('sub_category', ''))
                    if sc == 'curd':
                        curd_lits.append(v)
                    if int(row.get('is_raita', 0)) == 1 or 'raita' in sc:
                        raita_lits.append(v)

            curd_is_curd = model.NewBoolVar(f'curd_is_curd_{di}')
            link_any(model, curd_lits, curd_is_curd)
            curd_is_raita = model.NewBoolVar(f'curd_is_raita_{di}')
            link_any(model, raita_lits, curd_is_raita)

            # Each branch is guarded on the side actually being available.
            #
            # ``link_any`` pins its bool to 0 when the literal list is empty, so
            # an unguarded ``curd_is_raita == 1`` becomes ``0 == 1`` and takes the
            # whole plan INFEASIBLE the moment a cooldown, a theme filter or a
            # narrow source_pool leaves the curd_side pool with no raita. That is
            # a pool gap, not a reason to refuse the entire week — the rule can
            # only express a preference it has the items to express. Pairing is
            # still enforced wherever the items exist; ``diagnose()`` reports the
            # days where it could not be.
            if day_type == 'biryani':
                if raita_lits:
                    model.Add(curd_is_raita == 1)
            else:
                if raita_lits:
                    model.Add(curd_is_raita == 1).OnlyEnforceIf(rice_is_pulao)
                if curd_lits:
                    model.Add(curd_is_curd == 1).OnlyEnforceIf(
                        rice_is_pulao.Not())

    def diagnose(self, ctx: DiagnoseContext) -> List[Diagnostic]:
        """Report days where the yogurt-side pairing cannot be honoured.

        ``apply()`` no longer forces a raita it has no candidate for, so this is
        the surface that tells an admin the pairing silently did not happen. Both
        findings are WARNING: the plan is still valid and complete, it just does
        not pair the way the rulebook asks.
        """
        diags: List[Diagnostic] = []
        pool = ctx.pools.get('curd_side')
        active = ctx.active_base_slots
        if pool is None or (active is not None and 'curd_side' not in active):
            return diags

        def _is_raita(row) -> bool:
            sub = _norm_str(row.get('sub_category', ''))
            return int(row.get('is_raita', 0) or 0) == 1 or 'raita' in sub

        n_raita = sum(1 for _i, r in pool.iterrows() if _is_raita(r))
        n_curd = sum(
            1 for _i, r in pool.iterrows()
            if _norm_str(r.get('sub_category', '')) == 'curd'
        )
        biryani_days = [
            d for d in ctx.dates
            if ctx.day_types.get(d, '') == 'biryani'
            and (d, 'curd_side') not in (ctx.skip_cells or set())
        ]

        if biryani_days and n_raita == 0:
            diags.append(Diagnostic(
                rule=self.name, rule_type=self.rule_type.value,
                severity=DiagnosticSeverity.WARNING,
                phase=DiagnosticPhase.APPLY,
                message=(
                    f"{len(biryani_days)} biryani day(s) should be paired with a "
                    f"raita, but this client's curd_side pool contains no raita. "
                    f"Those days will get whatever curd_side item is available "
                    f"instead of the paired raita."
                ),
                suggestion=(
                    "Add raita items to the curd_side category, or widen this "
                    "client's source_pools so the shared raita items apply."
                ),
                affected={
                    'biryani_days': [d.isoformat() for d in biryani_days],
                    'raita_available': 0,
                },
            ))
        if n_curd == 0 and len(ctx.dates) > len(biryani_days):
            diags.append(Diagnostic(
                rule=self.name, rule_type=self.rule_type.value,
                severity=DiagnosticSeverity.WARNING,
                phase=DiagnosticPhase.APPLY,
                message=(
                    "Non-pulao days should be paired with plain curd, but the "
                    "curd_side pool contains no item with sub_category 'curd'. "
                    "Those days will get a raita or another side instead."
                ),
                suggestion=(
                    "Add a plain-curd item to curd_side, enable the separate "
                    "'curd' category for this counter, or widen source_pools."
                ),
                affected={'curd_available': 0, 'raita_available': n_raita},
            ))
        return diags
