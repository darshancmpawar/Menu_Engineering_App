"""
Menu regeneration: lock untouched cells, replace selected ones.

Uses similarity scoring to prefer items similar to the originals.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Dict, List, Set, Tuple

import pandas as pd

from ._helpers import (
    strip_color_suffix as _strip_color_suffix,
    cell_is_skipped as _cell_is_skipped,
    planned_dates as _planned_dates,
)
from .menu_solver import MenuSolver, SolverConfig, REGEN_SIMILARITY_PENALTY
from ..preprocessor.column_mapper import _norm_str

logger = logging.getLogger(__name__)


class MenuRegenerator:
    """
    Regenerates selected cells while keeping others locked.

    Usage:
        regen = MenuRegenerator(solver_args...)
        new_plan, dates = regen.regenerate(base_plan, replace_mask)
    """

    def __init__(
        self,
        pools: Dict[str, pd.DataFrame],
        df: pd.DataFrame,
        solver_config: SolverConfig,
        menu_rules=None,
        banned_by_date=None,
        ricebread_ban_day=None,
        recent_sigs=None,
        skip_cells=None,
    ):
        self.pools = pools
        self.df = df
        self.cfg = solver_config
        self.menu_rules = menu_rules or []
        self.banned_by_date = banned_by_date or {}
        self.ricebread_ban_day = ricebread_ban_day or {}
        self.recent_sigs = recent_sigs or set()
        self.skip_cells = skip_cells or set()
        # Mirror of MenuSolver.rule_failures from the last regenerate() call
        # so the API can forward soft-rule failures to the client.
        self.rule_failures: List[Dict[str, str]] = []

    def regenerate(
        self,
        base_plan: Dict[dt.date, Dict[str, str]],
        replace_mask: Dict[dt.date, Set[str]],
    ) -> Tuple[Dict, List[dt.date]]:
        """
        Regenerate selected cells.

        Args:
            base_plan: Original plan {date: {slot_id: item_string}}
            replace_mask: {date: {slot_ids_to_replace}}

        Returns:
            (new_plan, dates)
        """
        # Same horizon the solver will plan. Deriving this independently (a
        # plain contiguous start_date + i range) diverged from
        # MenuSolver.solve() for any non-Monday start, any weekend-skipping
        # client and every client with working_days: cells the user did not
        # select were left unlocked and silently re-solved.
        dates = _planned_dates(self.cfg)

        if sum(len(v) for v in replace_mask.values()) == 0:
            return base_plan, dates

        from src.constants import BASE_SLOT_NAMES
        from ..preprocessor.pool_builder import _expand_slots_in_order
        # Mirror the solver's slot set too, so we never lock a slot this
        # counter does not serve.
        base_slots = self.cfg.active_base_slots or BASE_SLOT_NAMES
        expanded_slots = _expand_slots_in_order(
            base_slots, self.cfg.slot_counts or {s: 1 for s in base_slots}
        )

        # Build locked dict
        locked = {}
        for d in dates:
            for slot_id in expanded_slots:
                if _cell_is_skipped(self.skip_cells, d, slot_id):
                    continue
                if slot_id not in replace_mask.get(d, set()):
                    val = base_plan.get(d, {}).get(slot_id, '')
                    locked[d, slot_id] = _norm_str(_strip_color_suffix(val))

        # Build forbidden dict
        forbidden = {}
        for d, slots in replace_mask.items():
            for slot_id in slots:
                if _cell_is_skipped(self.skip_cells, d, slot_id):
                    continue
                old_item = _norm_str(_strip_color_suffix(base_plan.get(d, {}).get(slot_id, '')))
                if old_item:
                    forbidden[d, slot_id] = {old_item}

        solver = MenuSolver(
            pools=self.pools,
            solver_config=self.cfg,
            menu_rules=self.menu_rules,
            banned_by_date=self.banned_by_date,
            ricebread_ban_day=self.ricebread_ban_day,
            recent_sigs=self.recent_sigs,
            skip_cells=self.skip_cells,
        )

        # Compute similarity scores
        # We need to solve once to get cells, then compute similarity
        # For now, use the solver's solve with locked/forbidden/similarity

        # First attempt: with forbidden (hard block old items)
        try:
            result = solver.solve(locked=locked, forbidden=forbidden, similarity=None)
            self.rule_failures = list(solver.rule_failures)
            return result
        except RuntimeError as exc:
            # Hard-blocking the old items left no feasible solution.
            # Fall back to allowing them with a heavy similarity penalty
            # so the regeneration still completes; log the original
            # failure so an operator can tell why we degraded.
            logger.info(
                "Regenerate hard-block infeasible, retrying with penalty: %s",
                exc,
            )

        # Fallback: allow old items but penalize them heavily
        similarity_penalties = {}
        for (d, slot_id), old_items in forbidden.items():
            for old_item in old_items:
                similarity_penalties[d, slot_id, old_item] = REGEN_SIMILARITY_PENALTY

        try:
            result = solver.solve(locked=locked, forbidden=None, similarity=similarity_penalties)
            self.rule_failures = list(solver.rule_failures)
            return result
        except RuntimeError as e:
            raise RuntimeError(f'Regeneration failed: {e}') from e
