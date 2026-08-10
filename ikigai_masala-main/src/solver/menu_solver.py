"""
Menu planning solver using Google OR-Tools CP-SAT.

Cell-based architecture: each (day, slot) pair has a pre-filtered candidate pool.
The solver creates one boolean variable per candidate per cell and selects exactly one.
"""

from __future__ import annotations

import datetime as dt
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

import pandas as pd
from ortools.sat.python import cp_model

from ._helpers import (
    weekday_type_for_config as _weekday_type_cfg,
    cell_is_skipped as _cell_is_skipped,
    planned_dates as _planned_dates,
    weekday_name as _weekday_name,
)
from ..menu_rules.base_menu_rule import BaseMenuRule, MenuRuleSeverity
from src.constants import (
    BASE_SLOT_NAMES, CONSTANT_ITEMS, EXEMPT_FROM_CUISINE,
    RICE_EXCLUDE_ITEMS, THEME_FALLBACK_SLOTS,
    COMBO_CATEGORIES, combo_minority_count, REPEATABLE_SLOTS,
)
from ..preprocessor.pool_builder import _base_slot, _slot_num, _expand_slots_in_order
from ..preprocessor.column_mapper import _norm_str, _norm_color, _to_bool01
from .solver_context import SolverContext


# ---------------------------------------------------------------------------
# Config dataclass (runtime solver configuration)
# ---------------------------------------------------------------------------

# Default candidate pool caps per base slot (used in multi-restart strategy)
DEFAULT_CAP_BY_SLOT: Dict[str, int] = {
    'rice': 1600, 'healthy_rice': 1200, 'veg_gravy': 1400,
    'nonveg_main': 1400, 'curd_side': 1400, 'veg_dry': 1100,
    'bread': 1100, 'starter': 1200, 'soup': 900, 'salad': 900,
    'dal': 1000, 'dessert': 1000, 'welcome_drink': 1000,
    'sambar': 900, 'rasam': 900,
}
DEFAULT_CAP = 900  # fallback for slots not in DEFAULT_CAP_BY_SLOT

# A slot whose distinct-item count exceeds its cell count by no more than this
# is reported as "tight" when a solve fails, to point an admin at the likely
# cause. It does NOT trigger any automatic relaxation — the only uniqueness that
# is ever lifted is for a slot that is arithmetically impossible (see
# UniqueItemsMenuRule.starved_slots).
UNIQUENESS_TIGHT_HEADROOM = 3

# Weekday token → full lowercase name (for client constant_items maps).
_WEEKDAY_ALIASES: Dict[str, str] = {
    'mon': 'monday', 'monday': 'monday',
    'tue': 'tuesday', 'tuesday': 'tuesday',
    'wed': 'wednesday', 'wednesday': 'wednesday',
    'thu': 'thursday', 'thursday': 'thursday',
    'fri': 'friday', 'friday': 'friday',
    'sat': 'saturday', 'saturday': 'saturday',
    'sun': 'sunday', 'sunday': 'sunday',
}


def _resolve_client_constant(
    spec: Any, weekday: str, iso_week: Optional[int] = None,
) -> Optional[str]:
    """Resolve a ``constant_items`` value for one weekday.

    * ``"Curd"`` → same string every day
    * ``{"friday": "raita"}`` → only on matching weekdays (full name or abbr)
    * ``["Mutton Biryani", "Fish Tikka Masala"]`` → **alternate across ISO
      weeks**: even ISO week → first item, odd → second (index = iso_week %
      len). Usable on its own (alternate every day) or as a weekday-map value
      (``{"wed": ["A", "B"]}`` → alternate only on Wednesdays). The engine's
      ISO-week parity — the same one `chinese_continental` uses — makes
      consecutive weeks flip, so "A this week, B next week" holds.
    """
    def _pick(value):
        if isinstance(value, list):
            if not value:
                return None
            return str(value[(iso_week or 0) % len(value)])
        return str(value) if value is not None else None

    if spec is None:
        return None
    if isinstance(spec, str):
        return spec
    if isinstance(spec, list):
        return _pick(spec)
    if isinstance(spec, dict):
        target = _WEEKDAY_ALIASES.get(weekday.lower(), weekday.lower())
        for key, value in spec.items():
            if not isinstance(key, str):
                continue
            if _WEEKDAY_ALIASES.get(key.strip().lower()) == target and value is not None:
                return _pick(value)
        return None
    return str(spec)


# Multi-restart strategy defaults
DEFAULT_CAP_MULTIPLIERS = (1, 2)  # try 1x then 2x candidate pool sizes
DEFAULT_RESTARTS_PER_MULTIPLIER = 4  # attempts per multiplier
DEFAULT_SEED_MULT_FACTOR = 1000  # seed formula: base + mult * FACTOR + restart * 17
DEFAULT_SEED_RESTART_STEP = 17

# Penalty/bonus weights
REGEN_SIMILARITY_PENALTY = -10_000  # penalty for re-selecting old items during regen


@dataclass
class SolverConfig:
    """Runtime configuration for the CP-SAT menu solver."""
    days: int = 5
    start_date: dt.date = field(default_factory=dt.date.today)
    seed: int = 7
    time_limit_sec: int = 240
    slot_counts: Optional[Dict[str, int]] = None
    active_base_slots: Optional[List[str]] = None
    # Constant items (white_rice / papad / pickle / chutney) to append to every
    # day. ``None`` means "all of them" (legacy behaviour); an explicit list
    # (possibly empty) is the per-client selection.
    const_slots: Optional[List[str]] = None
    # Per-client overlay from client_rules.json ``constant_items``. Values are
    # either a daily string or a weekday→string map. Applied after CONST_SLOTS.
    client_constant_items: Optional[Dict[str, Any]] = None
    # ``{(date, slot_id): item_name}`` for pins that name a real ontology dish.
    # These cells stay in the model with their candidate list narrowed to the
    # pinned item, so the rules see it; pins with no ontology match are stamped
    # post-solve via ``client_constant_items`` instead.
    forced_items: Optional[Dict[Any, str]] = None
    # Client-level weekday filter (lowercase full names). None = unrestricted.
    working_days: Optional[List[str]] = None
    explicit_dates: Optional[List[dt.date]] = None
    # Color constraints
    color_col: str = 'item_color'
    color_slots: List[str] = field(default_factory=lambda: [
        'starter', 'rice', 'veg_gravy', 'veg_dry', 'nonveg_main', 'dal', 'dessert',
    ])
    min_distinct_colors_per_day: int = 4
    min_distinct_colors_per_day_chinese: int = 4
    min_distinct_colors_per_day_biryani: int = 4
    max_same_color_per_day: int = 2      # rulebook 90: soft cap for every colour
    max_same_color_reach: int = 3        # rulebook 89: one colour may reach this
    max_colors_at_reach: int = 1         # rulebook 91: how many colours may exceed the soft cap
    ignore_rice_gravy_color_diff_on_chinese_day: bool = True
    # Premium flag column — set when the retained PremiumMenuRule is configured;
    # feeds day_premium_vars. (The old min/max-per-horizon knobs were removed
    # with the broad premium rule; the default ruleset uses selector_frequency
    # exact-1 rules instead.)
    premium_flag_col: Optional[str] = None
    # Rice exclusions — see src.constants.RICE_EXCLUDE_ITEMS.
    rice_exclude_items: Set[str] = field(default_factory=lambda: set(RICE_EXCLUDE_ITEMS))
    # Cuisine theme settings
    cuisine_col: str = 'cuisine_family'
    cuisine_south_value: str = 'south_indian'
    cuisine_north_value: str = 'north_indian'
    # Flag column names read by the nonveg theme rules. (The chinese-rice /
    # chinese-veg-gravy / chinese-starter / veg-biryani / raita flag knobs were
    # never read — the theme code uses the literal column names directly — so
    # they were removed.)
    f_chinese_nonveg: Optional[str] = 'is_chinese_chicken_gravy'
    f_nonveg_biryani: Optional[str] = 'is_nonveg_biryani'
    # Theme preferences
    prefer_theme_starter: bool = True
    # Solver strategy
    cap_by_slot: Dict[str, int] = field(default_factory=lambda: dict(DEFAULT_CAP_BY_SLOT))
    cap_default: int = DEFAULT_CAP
    cap_multipliers: Tuple[int, ...] = DEFAULT_CAP_MULTIPLIERS
    restarts_per_multiplier: int = DEFAULT_RESTARTS_PER_MULTIPLIER
    deterministic: bool = True
    #: How many CP-SAT search workers to use, as a *callable* so the value is
    #: re-read on every restart attempt (the API scales it down while another
    #: solve is active). Injected rather than imported: this module used to do
    #: `from api.concurrency import get_worker_count` inside the solve loop,
    #: which made the domain depend on the web layer and needed a try/except
    #: ImportError to stay runnable on its own. None = CP-SAT's own default.
    worker_count_provider: Optional[Callable[[], int]] = None
    # Per-client theme map (overrides global weekday_type)
    theme_map: Optional[Dict[str, str]] = None


# ---------------------------------------------------------------------------
# Cell — the core abstraction
# ---------------------------------------------------------------------------

class _Cell:
    """A single (day, slot) decision point with a pre-filtered candidate pool."""
    __slots__ = ('d_idx', 'date', 'slot_id', 'base_slot',
                 'cand_df', 'theme_pref_flags', 'x_vars', 'cand_rows')

    def __init__(self, d_idx: int, date: dt.date, slot_id: str,
                 base_slot: str, cand_df: pd.DataFrame,
                 theme_pref_flags: List[bool]):
        self.d_idx = d_idx
        self.date = date
        self.slot_id = slot_id
        self.base_slot = base_slot
        self.cand_df = cand_df
        self.theme_pref_flags = list(theme_pref_flags)
        self.x_vars: List[cp_model.IntVar] = []
        self.cand_rows: List[pd.Series] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _color_initial(x) -> str:
    c = _norm_color(x)
    if c == 'unknown':
        return ''
    base = c.split('_')[-1]
    return base[:1].upper() if base else ''


def _fmt_item_with_color(row: pd.Series, color_col: str) -> str:
    item = str(row.get('item', ''))
    ini = _color_initial(row.get(color_col, 'unknown'))
    return f'{item}({ini})' if ini else item


def _min_distinct_for_day(cfg: SolverConfig, day_type: str) -> int:
    if day_type == 'chinese':
        return cfg.min_distinct_colors_per_day_chinese
    if day_type == 'biryani':
        return cfg.min_distinct_colors_per_day_biryani
    return cfg.min_distinct_colors_per_day


def _combo_day_variant(base_slot: str, di: int, n_days: int) -> str:
    """Return the component course_type a combination slot uses on day *di*.

    The minority variant fills the last ``combo_minority_count(n_days)`` days
    of the horizon; the majority variant fills the rest. Deterministic by day
    index, so the split is stable across regenerate.
    """
    majority, minority = COMBO_CATEGORIES[base_slot]
    n_minority = combo_minority_count(n_days)
    return minority if di >= (n_days - n_minority) else majority


def _find_cells(cells: List[_Cell], di: int, base_slot: str) -> List[_Cell]:
    """Linear-scan lookup — kept for tests / ad-hoc use. Production uses
    ``_make_find_cells`` which backs the lookup with a dict."""
    return [c for c in cells if c.d_idx == di and c.base_slot == base_slot]


def _make_find_cells(cells: List[_Cell]):
    """Build an O(1) ``(d_idx, base_slot) -> [cells]`` lookup as a closure.

    Preserves the ``(cells, di, base_slot)`` signature used by rule modules;
    the first argument is ignored because the index already closes over the
    cell list.
    """
    index: Dict[Tuple[int, str], List[_Cell]] = {}
    for c in cells:
        index.setdefault((c.d_idx, c.base_slot), []).append(c)

    def _find(_cells, di: int, base_slot: str) -> List[_Cell]:
        return index.get((di, base_slot), [])

    return _find


def _link_any(model: cp_model.CpModel, lits: List, y) -> None:
    if not lits:
        model.Add(y == 0)
        return
    model.Add(sum(lits) >= y)
    for lit in lits:
        model.Add(lit <= y)


def _sample_with_priority(pool: pd.DataFrame, cap: int,
                          priority_mask: pd.Series,
                          rng: random.Random) -> pd.DataFrame:
    if len(pool) <= cap:
        return pool
    pm = priority_mask.reindex(pool.index).fillna(False).astype(bool)
    pri, oth = pool[pm], pool[~pm]
    if len(pri) >= cap:
        return pri.sample(cap, random_state=rng.randint(1, 10**9))
    if len(pri) == 0:
        return pool.sample(cap, random_state=rng.randint(1, 10**9))
    need = cap - len(pri)
    if len(oth) > need:
        oth = oth.sample(need, random_state=rng.randint(1, 10**9))
    return pd.concat([pri, oth], axis=0)


def _sample_cell_candidates(pool: pd.DataFrame, pref_mask: pd.Series,
                            cap: int, rng: random.Random) -> Tuple[pd.DataFrame, List[bool]]:
    pref2 = pref_mask.reindex(pool.index).fillna(False).astype(bool)
    if len(pool) > cap:
        if bool(pref2.any()):
            pool = _sample_with_priority(pool, cap, pref2, rng)
        else:
            pool = pool.sample(cap, random_state=rng.randint(1, 10**9))
    pref2 = pref2.reindex(pool.index).fillna(False).astype(bool)
    return pool.reset_index(drop=True), pref2.tolist()


# ---------------------------------------------------------------------------
# MenuSolver
# ---------------------------------------------------------------------------

class MenuSolver:
    """
    Cell-based CP-SAT menu planner.

    Each (day, slot) cell has a pre-filtered candidate pool. The solver
    picks exactly one candidate per cell subject to hard constraints.
    """

    def __init__(
        self,
        pools: Dict[str, pd.DataFrame],
        solver_config: SolverConfig,
        menu_rules: Optional[List[BaseMenuRule]] = None,
        banned_by_date: Optional[Dict[dt.date, Set[str]]] = None,
        ricebread_ban_day: Optional[Dict[dt.date, bool]] = None,
        recent_sigs: Optional[Set[str]] = None,
        skip_cells: Optional[Set[Tuple[dt.date, str]]] = None,
    ):
        self.pools = pools
        self.cfg = solver_config
        self.menu_rules = menu_rules or []
        self.banned_by_date = banned_by_date or {}
        self.ricebread_ban_day = ricebread_ban_day or {}
        self.recent_sigs = recent_sigs or set()
        self.skip_cells = skip_cells or set()
        # Soft rules that threw during apply / get_objective_terms.
        # Scoped to the winning attempt only — cleared at the start of
        # each restart so callers (API, regenerator) don't see failures
        # from cells that were discarded. On total failure the list
        # reflects the last attempt's failures, which is the most
        # actionable for diagnostics.
        self.rule_failures: List[Dict[str, Any]] = []
        # Stamped onto each rule_failures entry so diagnostics can tell
        # which multi-restart attempt produced which failure.
        self._current_attempt_seed: Optional[int] = None

    def _record_rule_failure(self, rule, phase: str, exc: BaseException) -> None:
        """Log a soft-rule failure with traceback and remember it on self."""
        name = getattr(rule, 'name', type(rule).__name__)
        logger.warning(
            "Soft rule %r failed during %s: %s",
            name, phase, exc, exc_info=True,
        )
        entry: Dict[str, Any] = {
            'rule': name,
            'phase': phase,
            'error': f'{type(exc).__name__}: {exc}',
            'attempt_seed': self._current_attempt_seed,
        }
        # Dedupe inside a single attempt so the same rule failing on
        # every cell of this attempt surfaces once. Across attempts,
        # rule_failures is cleared in solve() so there's no cross-
        # attempt bleed.
        if entry not in self.rule_failures:
            self.rule_failures.append(entry)

    def solve(self, locked=None, forbidden=None, similarity=None,
              n_alternates=0) -> Tuple[Any, List[dt.date]]:
        """
        Solve the menu plan with multi-restart strategy.

        Returns:
            ``(week_plan, dates)`` where ``week_plan`` maps
            ``date -> {slot_id: item_string}``.

            When ``n_alternates > 0`` the first element is instead a *list* of
            up to ``n_alternates + 1`` such plans ranked best-first (the primary
            plan followed by the closest-to-ideal distinct alternatives).
        """
        self.rule_failures = []
        self._current_attempt_seed = None
        # Horizon resolution (explicit_dates / start_date+days, then the
        # client-level working-days filter) is shared with the regenerator via
        # ``planned_dates`` so the two can never disagree about which days the
        # plan covers.
        dates = _planned_dates(self.cfg)
        if not dates:
            raise RuntimeError(
                'No planning dates: the requested horizon contains none of '
                f"the client's working days ({self.cfg.working_days}). "
                'Widen working_days or move the start date.'
            )
        base_slots = self.cfg.active_base_slots or BASE_SLOT_NAMES
        expanded_slots = _expand_slots_in_order(
            base_slots, self.cfg.slot_counts or {s: 1 for s in base_slots}
        )

        # The pre-filtered pool cache (item cooldown / theme filters / rice-bread
        # gap / combo split — the expensive DataFrame masking) is seed- and
        # cap-independent, so build it ONCE here rather than re-running it inside
        # every restart attempt. Only per-attempt sampling depends on rng/cap.
        base_slots_dedup = list(dict.fromkeys(_base_slot(s) for s in expanded_slots))
        pool_cache = self._build_day_base_pool_cache(
            dates, base_slots_dedup, expanded_slots
        )

        cap_multipliers = self.cfg.cap_multipliers
        restarts_per_mult = self.cfg.restarts_per_multiplier
        base_seed = int(self.cfg.seed)
        total_time = float(self.cfg.time_limit_sec)
        per_attempt_time = max(20.0, total_time / (len(cap_multipliers) * restarts_per_mult))
        # ``time_limit_sec`` is a TOTAL wall-clock budget, not a per-attempt one.
        # Without this deadline the multi-restart loop could run
        # (attempts × per_attempt_time) — e.g. 8 × 20s = 160s for a 60s
        # request — starving the solver-gate queue and outliving the HTTP
        # client timeout. Each attempt is capped at the smaller of its normal
        # slice and the time left in the budget; once the budget is spent we
        # stop restarting. The happy path (attempt 1 succeeds) is unaffected.
        deadline = time.monotonic() + total_time
        orig_seed, orig_time = self.cfg.seed, self.cfg.time_limit_sec
        state = {'last_err': None}

        def _attempt_cycle():
            """Run the full multi-restart cycle. Returns the result or None."""
            for mult in cap_multipliers:
                cap_default = self.cfg.cap_default * mult
                cap_by_slot = {k: v * mult for k, v in self.cfg.cap_by_slot.items()}

                for r in range(restarts_per_mult):
                    remaining = deadline - time.monotonic()
                    if remaining <= 1.0:
                        return None  # budget spent — don't start another attempt
                    attempt_seed = base_seed + mult * DEFAULT_SEED_MULT_FACTOR + r * DEFAULT_SEED_RESTART_STEP
                    rng = random.Random(attempt_seed)
                    self.cfg.seed = attempt_seed
                    self.cfg.time_limit_sec = max(1, int(min(per_attempt_time, remaining)))
                    # Reset per-attempt failure bucket and remember which
                    # attempt is running — callers that inspect
                    # rule_failures should only see the winning
                    # attempt's failures, not residue from attempts we
                    # abandoned with RuntimeError.
                    self._current_attempt_seed = attempt_seed
                    self.rule_failures = []

                    try:
                        cells = self._build_cells(
                            dates, expanded_slots, pool_cache,
                            cap_default, cap_by_slot, rng,
                        )
                        if n_alternates > 0:
                            chosen_list = self._solve_cpsat_ranked(
                                dates, cells, n_alternates, deadline,
                                locked=locked, similarity=similarity,
                                forbidden=forbidden,
                            )
                            return [
                                self._rows_to_week_plan(c, dates, expanded_slots)
                                for c in chosen_list
                            ]
                        chosen_rows = self._solve_cpsat(
                            dates, cells, locked=locked, similarity=similarity,
                            forbidden=forbidden,
                        )
                        return self._rows_to_week_plan(
                            chosen_rows, dates, expanded_slots
                        )
                    except RuntimeError as e:
                        state['last_err'] = e
                        continue
                if deadline - time.monotonic() <= 1.0:
                    return None
            return None

        try:
            result = _attempt_cycle()
            if result is not None:
                return result, dates

            # No plan. We deliberately do NOT retry with rules switched off.
            #
            # An over-constrained counter is a configuration conflict, and the
            # useful output is the conflict, not a menu that quietly abandons
            # the rules the client is paying for. The only relaxation this
            # solver performs is for a slot that is *arithmetically* impossible
            # — fewer distinct eligible items than days to fill — which
            # UniqueItemsMenuRule handles up front, minimally, and reports. A
            # conflict between two satisfiable rules is surfaced here instead,
            # naming the slots most likely responsible so an admin can fix the
            # config rather than guess.
            tight = self._tight_slots(
                dates, expanded_slots, pool_cache, UNIQUENESS_TIGHT_HEADROOM,
            )
            detail = ''
            if tight:
                detail = (
                    ' Tightest slot(s) for this counter — '
                    + ', '.join(
                        f'{s} ({n} distinct item(s) for {c} day-slot(s))'
                        for s, n, c in sorted(tight)
                    )
                    + '. Check the rules scoped to them (frequency caps, theme'
                    ' filters, day restrictions), widen this client\'s'
                    ' source_pools, or reduce the slot count.'
                )
            raise RuntimeError(
                'No feasible plan found: the rules configured for this counter '
                'cannot all be satisfied over the requested horizon.' + detail
            ) from state['last_err']
        finally:
            self.cfg.seed, self.cfg.time_limit_sec = orig_seed, orig_time

    def _tight_slots(self, dates, expanded_slots, pool_cache, headroom):
        """Slots whose eligible pool leaves little room for uniqueness.

        Returns ``{(base_slot, distinct_items, cells_to_fill)}`` for slots whose
        ``distinct_items - cells_to_fill`` is at or below *headroom*. Used only
        to make an infeasibility message actionable — it names where an admin
        should look. Repeatable slots are excluded; they are exempt from
        uniqueness already.
        """
        stats: Dict[str, Dict[str, Any]] = {}
        for di, d in enumerate(dates):
            for slot_id in expanded_slots:
                if _cell_is_skipped(self.skip_cells, d, slot_id):
                    continue
                base = _base_slot(slot_id)
                if base in REPEATABLE_SLOTS:
                    continue
                entry = stats.setdefault(base, {'cells': 0, 'items': set()})
                entry['cells'] += 1
                cached = pool_cache.get((di, slot_id))
                if not cached:
                    continue
                pool = cached[0]
                if len(pool):
                    entry['items'].update(
                        _norm_str(v) for v in pool['item'].tolist()
                    )
        out = set()
        for base, entry in stats.items():
            distinct = len({i for i in entry['items'] if i})
            if distinct - entry['cells'] <= headroom:
                out.add((base, distinct, entry['cells']))
        return out

    # ----- Cell building -----

    def _build_cells(
        self, dates: List[dt.date], expanded_slots: List[str], cache: Dict,
        cap_default: int, cap_by_slot: Dict[str, int], rng: random.Random,
    ) -> List[_Cell]:
        # ``cache`` (the seed/cap-independent pre-filtered pools) is built once
        # in solve() and reused across restart attempts; only the per-attempt
        # sampling below depends on rng/cap.
        cells: List[_Cell] = []

        for di, d in enumerate(dates):
            for slot_id in expanded_slots:
                base = _base_slot(slot_id)
                if _cell_is_skipped(self.skip_cells, d, slot_id):
                    continue
                pool2, pref_mask, day_type = cache[di, slot_id]

                if len(pool2) == 0:
                    extra = ''
                    if base == 'bread' and self.ricebread_ban_day.get(d, False):
                        extra = ' (rice-bread banned by gap rule)'
                    raise RuntimeError(
                        f'Empty pool after filters: {d.isoformat()} '
                        f'slot={slot_id} day_type={day_type}{extra}'
                    )

                # A client constant naming a real ontology dish is solved, not
                # stamped: restricting the cell to that one candidate pins the
                # dish while leaving it visible to every other rule, so the rest
                # of the day is composed around it (its colour counts toward
                # colour variety, its cuisine toward cuisine variety, and it
                # cannot be duplicated elsewhere). A pin naming a dish the
                # ontology does not carry has no candidate to restrict to and is
                # stamped verbatim after the solve instead.
                forced = (self.cfg.forced_items or {}).get((d, slot_id))
                if forced:
                    match = pool2[
                        pool2['item'].astype(str).str.strip().str.lower()
                        == forced
                    ]
                    if len(match):
                        # Narrow the pool only. ``pref_mask`` is index-aligned
                        # and _sample_cell_candidates reindexes it onto whatever
                        # pool it is given, so it must be left intact.
                        pool2 = match
                    else:
                        logger.info(
                            "%s on %s: pinned dish %r is not eligible for this "
                            "slot today (filtered out or absent from the pool); "
                            "solving the cell normally",
                            slot_id, d.isoformat(), forced,
                        )

                cap = cap_by_slot.get(base, cap_default)
                sampled, theme_flags = _sample_cell_candidates(pool2, pref_mask, cap, rng)
                cells.append(_Cell(di, d, slot_id, base, sampled, theme_flags))

        return cells

    def _build_day_base_pool_cache(
        self, dates: List[dt.date], base_slots: List[str],
        expanded_slots: List[str],
    ) -> Dict:
        cache = {}

        # Build shared filter context for rule pre_filter_pool calls.
        # `extra_repeatable` carries the rule-declared staples so the cooldown
        # pre-filter exempts the same dishes unique_items does — one
        # declaration, both consumers.
        base_filter_ctx: Dict[str, Any] = {
            'cfg': self.cfg,
            'banned_by_date': self.banned_by_date,
            'ricebread_ban_day': self.ricebread_ban_day,
            'pools': self.pools,
            'extra_repeatable': self._declared_repeatable(),
        }

        for di, d in enumerate(dates):
            day_type = _weekday_type_cfg(d, self.cfg.theme_map)

            # First pass: build base-slot level pools (shared across slot numbers)
            base_pools: Dict[str, pd.DataFrame] = {}
            for base in base_slots:
                pool2 = self.pools[base].copy()

                # Exclude steamed rice etc. from flavor rice/healthy_rice
                if base in ('rice', 'healthy_rice') and len(pool2) > 0:
                    pool2 = pool2[~pool2['item'].isin(self.cfg.rice_exclude_items)]

                # Apply rule pre-filters (item cooldown, ricebread gap,
                # theme slot filters, etc.)
                filter_ctx = {**base_filter_ctx, 'slot_num': None}
                for rule in self.menu_rules:
                    pool2 = rule.pre_filter_pool(pool2, d, base, day_type, filter_ctx)

                # Combination category: restrict this day's pool to the
                # majority or minority component by course_type, so the combo
                # slot splits across the week (e.g. dal 3 days, rasam 2 days).
                if base in COMBO_CATEGORIES and len(pool2) > 0:
                    variant = _combo_day_variant(base, di, len(dates))
                    v = pool2[pool2['course_type'] == variant]
                    if len(v) > 0:
                        pool2 = v

                base_pools[base] = pool2

            # Second pass: per expanded slot (handles slot_num for nonveg_dry etc.)
            for slot_id in expanded_slots:
                base = _base_slot(slot_id)
                slot_num = _slot_num(slot_id)
                pool2 = base_pools[base]

                # Apply slot-number-aware pre-filters (e.g. nonveg dry preference)
                if slot_num is not None and slot_num >= 2:
                    filter_ctx = {**base_filter_ctx, 'slot_num': slot_num}
                    for rule in self.menu_rules:
                        pool2 = rule.pre_filter_pool(pool2, d, base, day_type, filter_ctx)

                # Theme preference mask (for sampling priority + fallback penalty)
                pref_mask = self._compute_theme_pref_mask(pool2, base, day_type)

                cache[di, slot_id] = (pool2, pref_mask, day_type)
        return cache

    @staticmethod
    def _compute_theme_pref_mask(pool: pd.DataFrame, base_slot: str,
                                 day_type: str) -> pd.Series:
        """Mark items matching the day's theme as preferred.

        Only meaningful for THEME_FALLBACK_SLOTS (starter, veg_dry) where the
        pool is NOT hard-filtered by cuisine but we still want to prefer
        theme-matching items via sampling priority and fallback penalty.
        """
        if len(pool) == 0 or base_slot not in THEME_FALLBACK_SLOTS:
            return pd.Series(False, index=pool.index)

        if day_type == 'south' and 'cuisine_family' in pool.columns:
            return pool['cuisine_family'].map(_norm_str) == 'south_indian'
        if day_type == 'north' and 'cuisine_family' in pool.columns:
            return pool['cuisine_family'].map(_norm_str) == 'north_indian'
        if day_type == 'chinese':
            # Chinese starters have flag; veg_dry uses text heuristics
            if base_slot == 'starter' and 'is_chinese_starter' in pool.columns:
                return pool['is_chinese_starter'].map(_to_bool01) == 1
            # veg_dry: chinese side mask heuristic
            text = (pool['item'].astype(str) + ' ' +
                    pool.get('sub_category', pd.Series('', index=pool.index)).astype(str))
            text = text.str.lower()
            return (
                text.str.contains('chinese', na=False) |
                text.str.contains('manchurian', na=False) |
                text.str.contains('schezwan', na=False) |
                text.str.contains('szechuan', na=False) |
                text.str.contains('gobi.65', na=False) |
                text.str.contains('baby.corn', na=False) |
                text.str.contains('noodle', na=False) |
                text.str.contains('chilli', na=False)
            )
        # mix, biryani, holiday: no preference
        return pd.Series(False, index=pool.index)

    # ----- CP-SAT model -----

    def _assemble_model(
        self, dates: List[dt.date], cells: List[_Cell],
        locked=None, similarity=None, forbidden=None,
    ) -> cp_model.CpModel:
        """Build the full CP-SAT model (decision vars + colour constraints +
        every rule's constraints + the tiered objective) for these cells.
        Populates ``cell.x_vars``/``cell.cand_rows`` as a side effect so the
        caller can read the solution back."""
        rng = random.Random(self.cfg.seed)
        model = cp_model.CpModel()
        day_types = [_weekday_type_cfg(d, self.cfg.theme_map) for d in dates]

        known_colors, known_welcome_colors = self._collect_known_colors(cells)
        build_result = self._build_decision_variables(
            model, cells, day_types, locked=locked, forbidden=forbidden,
        )
        (item_to_vars, day_color_vars, day_rice_color_vars,
         day_gravy_color_vars, day_premium_vars, day_welcome_color_vars,
         monday_south_lits, monday_north_lits, theme_fallback_bools) = build_result

        context = self._build_context(
            cells, dates, day_types,
            item_to_vars, day_color_vars, day_rice_color_vars,
            day_gravy_color_vars, day_premium_vars, day_welcome_color_vars,
            monday_south_lits, monday_north_lits, theme_fallback_bools,
            known_colors, known_welcome_colors,
        )

        # Built-in color constraints (uniqueness is handled by UniqueItemsMenuRule)
        self._add_color_constraints(model, dates, day_types, known_colors,
                                    day_color_vars, day_rice_color_vars,
                                    day_gravy_color_vars, cells)

        self._apply_rules_and_objective(model, cells, rng, similarity, context)
        return model

    def _solve_cpsat(
        self, dates: List[dt.date], cells: List[_Cell],
        locked=None, similarity=None, forbidden=None,
    ) -> Dict:
        model = self._assemble_model(dates, cells, locked, similarity, forbidden)
        solver = self._configure_and_solve(model)
        return self._extract_solution_rows(solver, cells, dates)

    def _solve_cpsat_ranked(
        self, dates: List[dt.date], cells: List[_Cell], n_alternates: int,
        deadline: float, locked=None, similarity=None, forbidden=None,
    ) -> List[Dict]:
        """Return up to ``n_alternates + 1`` distinct menus ranked best-first.

        Solves the model, then repeatedly forbids the exact assignment just
        found (a no-good cut) and re-maximizes the *same* tiered objective, so
        each next menu is the closest-to-ideal one that differs from all
        previous — deliberately not random diversification. Stops early if no
        more distinct menus exist or the wall-clock deadline is hit."""
        model = self._assemble_model(dates, cells, locked, similarity, forbidden)
        per_solve = self.cfg.time_limit_sec
        out: List[Dict] = []
        for k in range(n_alternates + 1):
            remaining = deadline - time.monotonic()
            if out and remaining <= 1.0:
                break
            self.cfg.time_limit_sec = max(1, int(min(per_solve, max(1.0, remaining))))
            try:
                solver = self._configure_and_solve(model)
            except RuntimeError:
                if out:
                    break   # no further distinct menu (or out of time) — return what we have
                raise       # not even the primary solved → let the restart loop react
            out.append(self._extract_solution_rows(solver, cells, dates))
            if k == n_alternates:
                break
            # No-good cut: at least one cell must differ from this menu.
            picked = []
            for cell in cells:
                j = next(idx for idx, v in enumerate(cell.x_vars) if solver.Value(v) == 1)
                picked.append(cell.x_vars[j])
            model.Add(sum(picked) <= len(picked) - 1)
        return out

    def _declared_repeatable(self):
        """Collect ``repeatable_item_flags()`` from every rule that declares one.

        A rule that deliberately repeats a dish (see FixedDailyItemRule) declares
        the selector it needs exempted from ``unique_items``, so the rule creating
        the repetition and the rule forbidding one cannot disagree. Scoped to the
        client whose config carries the rule, unlike the ontology-wide
        REPEATABLE_ITEM_FLAGS_BY_SLOT.
        """
        out: Dict[str, List[Any]] = {}
        for rule in (self.menu_rules or []):
            fn = getattr(rule, 'repeatable_item_flags', None)
            if not callable(fn):
                continue
            try:
                for slot, matchers in (fn() or {}).items():
                    out.setdefault(slot, []).append(matchers)
            except Exception as exc:  # noqa: BLE001 — a bad rule must not block
                logger.warning(
                    "%s.repeatable_item_flags() raised: %s",
                    getattr(rule, 'name', type(rule).__name__), exc)
        return out

    def _build_context(
        self, cells, dates, day_types,
        item_to_vars, day_color_vars, day_rice_color_vars,
        day_gravy_color_vars, day_premium_vars, day_welcome_color_vars,
        monday_south_lits, monday_north_lits, theme_fallback_bools,
        known_colors, known_welcome_colors,
    ) -> SolverContext:
        """Assemble the rule-facing context.

        Returns a plain ``dict`` typed as :class:`SolverContext`
        (a ``TypedDict``), so rules keep using ``.get()`` access while
        the solver↔rule contract stays statically checkable.
        """
        return {
            'cells': cells,
            'dates': dates,
            'day_types': day_types,
            'item_to_vars': item_to_vars,
            'day_color_vars': day_color_vars,
            'day_rice_color_vars': day_rice_color_vars,
            'day_gravy_color_vars': day_gravy_color_vars,
            'day_premium_vars': day_premium_vars,
            'day_welcome_color_vars': day_welcome_color_vars,
            'monday_south_lits': monday_south_lits,
            'monday_north_lits': monday_north_lits,
            'theme_fallback_bools': theme_fallback_bools,
            'known_colors': known_colors,
            'known_welcome_colors': known_welcome_colors,
            'cfg': self.cfg,
            # Slot -> [(include_matcher, exclude_matcher)] declared by rules that
            # deliberately repeat a dish (see FixedDailyItemRule). unique_items
            # folds these into its repeatable set, so the rule that creates a
            # repetition and the rule that forbids one cannot disagree.
            'extra_repeatable': self._declared_repeatable(),
            'recent_sigs': self.recent_sigs,
            'find_cells_fn': _make_find_cells(cells),
            'link_any_fn': _link_any,
        }

    def _apply_rules_and_objective(self, model, cells, rng, similarity, context) -> None:
        """Run every rule's ``apply`` then assemble the objective.

        Hard rules (default severity) that raise cause the solve to fail
        rather than silently drop their constraint; soft rules only warn.
        """
        for rule in self.menu_rules:
            try:
                rule.apply(model, {}, None, context)
            except Exception as e:  # noqa: BLE001 — severity decides what happens
                severity = getattr(rule, 'severity', MenuRuleSeverity.HARD)
                if severity == MenuRuleSeverity.HARD:
                    raise RuntimeError(
                        f"Hard menu rule '{rule.name}' failed: {type(e).__name__}: {e}"
                    ) from e
                # Soft rule. Record every exception type — previously only
                # ValueError/KeyError/AttributeError were caught, so a
                # buggy soft rule raising TypeError or RuntimeError would
                # crash the whole solve and leak details via the 500,
                # defeating the "soft rules never block" contract.
                self._record_rule_failure(rule, 'apply', e)
        self._build_objective(model, cells, rng, similarity, context)

    def _configure_and_solve(self, model) -> cp_model.CpSolver:
        """Set CP-SAT parameters, solve, and translate infeasibility into a
        RuntimeError. Returns the solver so callers can read variable values.
        """
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = float(self.cfg.time_limit_sec)
        solver.parameters.random_seed = int(self.cfg.seed)
        if self.cfg.deterministic:
            solver.parameters.num_search_workers = 1
        elif self.cfg.worker_count_provider is not None:
            solver.parameters.num_search_workers = int(
                self.cfg.worker_count_provider())
        else:
            solver.parameters.num_search_workers = 8
        solver.parameters.cp_model_presolve = True

        status = solver.Solve(model)
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return solver
        if status == cp_model.INFEASIBLE:
            raise RuntimeError('No feasible plan found (INFEASIBLE).')
        if status == cp_model.UNKNOWN:
            raise RuntimeError('No feasible plan found (TIME LIMIT).')
        if status == cp_model.MODEL_INVALID:
            raise RuntimeError('CP-SAT model invalid.')
        raise RuntimeError(f'CP-SAT failed with status={status}.')

    def _collect_known_colors(self, cells: List[_Cell]) -> Tuple[List[str], List[str]]:
        known_colors: Set[str] = set()
        known_welcome: Set[str] = set()
        for cell in cells:
            if cell.base_slot in self.cfg.color_slots:
                for c in cell.cand_df[self.cfg.color_col].tolist():
                    col = _norm_color(c)
                    if col != 'unknown':
                        known_colors.add(col)
            if cell.base_slot == 'welcome_drink':
                for c in cell.cand_df[self.cfg.color_col].tolist():
                    col = _norm_color(c)
                    if col != 'unknown':
                        known_welcome.add(col)
        return sorted(known_colors), sorted(known_welcome)

    def _build_decision_variables(
        self, model: cp_model.CpModel, cells: List[_Cell],
        day_types: List[str], locked=None, forbidden=None,
    ):
        item_to_vars: Dict[str, List] = {}
        day_color_vars: Dict[Tuple, List] = {}
        day_rice_color_vars: Dict[Tuple, List] = {}
        day_gravy_color_vars: Dict[Tuple, List] = {}
        day_premium_vars: Dict[int, List] = {}
        day_welcome_color_vars: Dict[Tuple, List] = {}
        monday_south_lits: List = []
        monday_north_lits: List = []
        theme_fallback_bools: List = []

        for cell in cells:
            di = cell.d_idx
            slot_id = cell.slot_id
            base = cell.base_slot
            x_vars: List = []
            cand_rows: List = []

            for j in range(len(cell.cand_df)):
                row = cell.cand_df.iloc[j]
                item_base = _norm_str(row.get('item', ''))
                var = model.NewBoolVar(f'x_d{di}_{slot_id}_{j}')
                x_vars.append(var)
                cand_rows.append(row)

                # Repeatable slots (e.g. the plain-curd station) are exempt
                # from the unique-items constraint: don't track their vars so
                # the same item may appear on every day.
                if base not in REPEATABLE_SLOTS:
                    item_to_vars.setdefault(item_base, []).append(var)

                # Premium tracking
                if self.cfg.premium_flag_col and int(row.get(self.cfg.premium_flag_col, 0)) == 1:
                    day_premium_vars.setdefault(di, []).append(var)

                # Color tracking
                if base in self.cfg.color_slots:
                    col = _norm_color(row.get(self.cfg.color_col, 'unknown'))
                    if col != 'unknown':
                        day_color_vars.setdefault((di, col), []).append(var)
                        if base == 'rice':
                            day_rice_color_vars.setdefault((di, col), []).append(var)
                        elif base == 'veg_gravy':
                            day_gravy_color_vars.setdefault((di, col), []).append(var)

                if base == 'welcome_drink':
                    col = _norm_color(row.get(self.cfg.color_col, 'unknown'))
                    if col != 'unknown':
                        day_welcome_color_vars.setdefault((di, col), []).append(var)

                # Monday mix tracking
                if day_types[di] == 'mix' and base not in EXEMPT_FROM_CUISINE:
                    cf = _norm_str(row.get(self.cfg.cuisine_col, ''))
                    if cf == self.cfg.cuisine_south_value:
                        monday_south_lits.append(var)
                    elif cf == self.cfg.cuisine_north_value:
                        monday_north_lits.append(var)

                # Locked/forbidden
                if locked and (cell.date, slot_id) in locked:
                    if item_base != _norm_str(locked[cell.date, slot_id]):
                        model.Add(var == 0)
                if forbidden and (cell.date, slot_id) in forbidden:
                    if item_base in forbidden[cell.date, slot_id]:
                        model.Add(var == 0)

            # Exactly one candidate per cell
            model.Add(sum(x_vars) == 1)
            cell.x_vars = x_vars
            cell.cand_rows = cand_rows

            # Theme fallback tracking
            if cell.base_slot in THEME_FALLBACK_SLOTS:
                pref_flags = [bool(v) for v in cell.theme_pref_flags]
                if pref_flags and any(pref_flags) and not all(pref_flags):
                    fallback_lits = [v for v, pf in zip(x_vars, pref_flags) if not pf]
                    if fallback_lits:
                        fb = model.NewBoolVar(f'theme_fallback_{di}_{slot_id}')
                        _link_any(model, fallback_lits, fb)
                        theme_fallback_bools.append(fb)

        return (item_to_vars, day_color_vars, day_rice_color_vars,
                day_gravy_color_vars, day_premium_vars, day_welcome_color_vars,
                monday_south_lits, monday_north_lits, theme_fallback_bools)

    # ----- Built-in constraints -----

    def _add_color_constraints(self, model, dates, day_types, known_colors,
                               day_color_vars, day_rice_color_vars,
                               day_gravy_color_vars, cells=None):
        cfg = self.cfg
        # Upper bound on achievable distinct colours in a day = the number of
        # colour-bearing slots the counter actually serves. A small counter
        # (e.g. a Chinese station with only rice + veg_gravy) can never show
        # more distinct colours than it has slots, so the configured minimum
        # must be clamped to that or the day is trivially INFEASIBLE.
        color_bases = set(cfg.color_slots)
        active = cfg.active_base_slots or BASE_SLOT_NAMES
        counts = cfg.slot_counts or {s: 1 for s in active}
        n_color_slots = sum(
            1 for s in _expand_slots_in_order(active, counts)
            if _base_slot(s) in color_bases
        )
        # …and clamp PER DAY, because a day can have fewer colour cells than the
        # counter's config implies: skip_cells removes them. Amadeus Pune serves
        # five colour slots but on Sunday only rice and dessert (the veg gravy,
        # veg dry and dal are restricted off that day) — a config-derived clamp
        # of 3 asked two cells for three distinct colours, which is INFEASIBLE
        # with nothing pointing at the colour rule. The "colours present in the
        # day's pools" cap below cannot catch it: colours available and cells
        # available are different numbers.
        cells_per_day: Dict[int, int] = {}
        for cell in (cells or ()):
            if cell.base_slot in color_bases:
                cells_per_day[cell.d_idx] = cells_per_day.get(cell.d_idx, 0) + 1
        for di, _ in enumerate(dates):
            day_type = day_types[di]
            day_color_cells = (
                cells_per_day.get(di, 0) if cells is not None else n_color_slots
            )
            min_dist = min(
                _min_distinct_for_day(cfg, day_type),
                n_color_slots,
                day_color_cells,
            )

            # Per-colour occurrence caps (rulebook 89-91): every colour may
            # appear at most `soft_cap` times (rule 90), EXCEPT up to
            # `max_colors_at_reach` colour(s) may go as high as `reach`
            # (rules 89 + 91). Falls back to a uniform cap when reach <=
            # soft_cap or no colour is allowed to exceed it.
            soft_cap = cfg.max_same_color_per_day
            reach = max(soft_cap, cfg.max_same_color_reach)
            reach_bools = []
            for col in known_colors:
                lits = day_color_vars.get((di, col), [])
                if not lits:
                    continue
                if reach > soft_cap and cfg.max_colors_at_reach > 0:
                    b = model.NewBoolVar(f'color_reach_{di}_{col}')
                    # b == 0 -> sum <= soft_cap ; b == 1 -> sum <= reach
                    model.Add(sum(lits) <= soft_cap + (reach - soft_cap) * b)
                    reach_bools.append(b)
                else:
                    model.Add(sum(lits) <= soft_cap)
            if reach_bools:
                model.Add(sum(reach_bools) <= cfg.max_colors_at_reach)

            y_vars = []
            for col in known_colors:
                lits = day_color_vars.get((di, col), [])
                if not lits:
                    continue
                y = model.NewBoolVar(f'y_color_{di}_{col}')
                _link_any(model, lits, y)
                y_vars.append(y)
            # Also cap by the number of colours actually present in the day's
            # candidate pools (len(y_vars)); requiring more than exist is
            # infeasible regardless of slot count.
            if y_vars:
                model.Add(sum(y_vars) >= min(min_dist, len(y_vars)))

            if not (cfg.ignore_rice_gravy_color_diff_on_chinese_day and day_type == 'chinese'):
                for col in known_colors:
                    r_lits = day_rice_color_vars.get((di, col), [])
                    g_lits = day_gravy_color_vars.get((di, col), [])
                    if r_lits and g_lits:
                        model.Add(sum(r_lits) + sum(g_lits) <= 1)

    # ----- Objective -----

    def _build_objective(self, model, cells, rng, similarity, context):
        obj_terms = []

        if similarity:
            for cell in cells:
                for var, row in zip(cell.x_vars, cell.cand_rows):
                    sc = int(similarity.get(
                        (cell.date, cell.slot_id, _norm_str(row.get('item', ''))), 0
                    ))
                    if sc:
                        obj_terms.append(var * sc)
            for cell in cells:
                for var in cell.x_vars:
                    obj_terms.append(var * rng.randint(0, 3))
        else:
            for cell in cells:
                for var in cell.x_vars:
                    obj_terms.append(var * rng.randint(0, 1000))

        # Collect objective terms from rules. These are always treated as
        # soft — get_objective_terms() only shapes the objective, so a
        # failing rule just means "that preference doesn't apply this
        # solve". Catch Exception (not a narrow tuple) so a buggy rule
        # raising TypeError / RuntimeError / anything else is recorded
        # rather than crashing the solve.
        for rule in self.menu_rules:
            try:
                terms = rule.get_objective_terms(model, context)
                obj_terms.extend(terms)
            except Exception as e:  # noqa: BLE001 — recorded, not swallowed silently
                self._record_rule_failure(rule, 'get_objective_terms', e)

        if obj_terms:
            model.Maximize(sum(obj_terms))

    # ----- Solution extraction -----

    def _extract_solution_rows(self, solver, cells, dates):
        chosen = {d: {} for d in dates}
        for cell in cells:
            pick_idx = next(
                (j for j, var in enumerate(cell.x_vars) if solver.Value(var) == 1),
                None,
            )
            if pick_idx is None:
                raise RuntimeError('Solver solution missing selection in a cell.')
            chosen[cell.date][cell.slot_id] = cell.cand_rows[pick_idx]
        return chosen

    def _rows_to_week_plan(self, chosen_rows, dates, expanded_slots):
        week_plan = {}
        client_consts = getattr(self.cfg, 'client_constant_items', None) or {}
        for d in dates:
            day_out = {}
            for slot_id in expanded_slots:
                if slot_id in chosen_rows[d]:
                    day_out[slot_id] = _fmt_item_with_color(
                        chosen_rows[d][slot_id], self.cfg.color_col
                    )
            # Append the client's selected constant items. None = all
            # (legacy default); an explicit list scopes them per-client.
            #
            # Constant slots are stamped, not solved, so they have no cell for
            # ``skip_cells`` to suppress — a ``slot_day_restriction`` on
            # white_rice/papad/pickle/chutney used to be a silent no-op and the
            # staple appeared every day anyway. Honour skip_cells here so a day
            # restriction (or a whole-slot client constant) can genuinely remove
            # a constant slot from a given day.
            const_keys = (
                list(CONSTANT_ITEMS) if self.cfg.const_slots is None
                else list(self.cfg.const_slots)
            )
            for k in const_keys:
                if k not in CONSTANT_ITEMS:
                    continue
                if _cell_is_skipped(self.skip_cells, d, k):
                    continue
                day_out[k] = CONSTANT_ITEMS[k]
            # Per-client overlay (after globals). Day-specific maps only stamp
            # on matching weekdays; daily strings stamp every day.
            if client_consts:
                weekday = _weekday_name(d)
                forced = self.cfg.forced_items or {}
                for slot, spec in client_consts.items():
                    # A pin the solver placed itself is already in day_out with
                    # its colour suffix; stamping the raw text over it would
                    # throw that away and re-hide the item from the rendered
                    # menu's colour column.
                    if (d, slot) in forced:
                        continue
                    value = _resolve_client_constant(
                        spec, weekday, d.isocalendar()[1])
                    if value is not None:
                        day_out[slot] = value
            week_plan[d] = day_out
        return week_plan
