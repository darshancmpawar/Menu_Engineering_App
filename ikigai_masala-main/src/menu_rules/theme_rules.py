"""
Theme-related menu rules.

Four rules that together enforce the weekday → cuisine-theme mapping:

* :class:`ThemeDayMenuRule` — hard constraint: Monday 'mix' day requires
  at least one south-cuisine and one north-cuisine item.
* :class:`ThemeSlotFilterRule` — pre-filter: on chinese / biryani /
  south / north days, narrow each slot's pool to items that fit the
  day's theme.
* :class:`ThemeStarterPreferenceRule` — soft bonus for starters that
  match the day's theme.
* :class:`ThemeFallbackPenaltyRule` — soft penalty for non-theme items
  chosen in starter / veg_dry slots when a theme item was available.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Set

import pandas as pd
from ortools.sat.python import cp_model

from src.constants import BASE_SLOT_NAMES, EXEMPT_FROM_CUISINE

from ..preprocessor.column_mapper import _norm_str, _to_bool01
from .base_menu_rule import (
    BaseMenuRule,
    Diagnostic,
    DiagnosticPhase,
    DiagnosticSeverity,
    DiagnoseContext,
    MenuRuleType,
    MenuRuleSeverity,
)


# ---------------------------------------------------------------------------
# ThemeDayMenuRule
# ---------------------------------------------------------------------------


class ThemeDayMenuRule(BaseMenuRule):
    """
    Enforces Monday mix constraint: >= 1 south + >= 1 north item.

    Config:
    {
        "type": "theme_day",
        "name": "monday_mix"
    }
    """

    def __init__(self, rule_config: Dict[str, Any]):
        super().__init__(rule_config)
        self.rule_type = MenuRuleType.THEME_DAY

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        day_types = context.get('day_types', [])
        south_lits = context.get('monday_south_lits', [])
        north_lits = context.get('monday_north_lits', [])

        if any(dt_ == 'mix' for dt_ in day_types):
            if south_lits:
                model.Add(sum(south_lits) >= 1)
            if north_lits:
                model.Add(sum(north_lits) >= 1)

    def diagnose(self, ctx: DiagnoseContext) -> List[Diagnostic]:
        """For every mix-themed day, verify the non-exempt slot pools
        carry at least one south_indian AND one north_indian item.

        The CP-SAT constraint is ``sum(south_lits) >= 1`` and
        ``sum(north_lits) >= 1``, so a 0-count in either direction is
        a guaranteed infeasibility — emit ERROR.
        """
        diags: List[Diagnostic] = []
        if not any(t == 'mix' for t in ctx.day_types.values()):
            return diags

        cuisine_col = ctx.cfg.cuisine_col if ctx.cfg else 'cuisine_family'
        south_val = ctx.cfg.cuisine_south_value if ctx.cfg else 'south_indian'
        north_val = ctx.cfg.cuisine_north_value if ctx.cfg else 'north_indian'
        base_slots = ctx.active_base_slots or list(BASE_SLOT_NAMES)

        for d in ctx.dates:
            if ctx.day_types.get(d) != 'mix':
                continue
            day_label = d.strftime('%A %d %b')
            south_total = north_total = 0

            for base in base_slots:
                if base in EXEMPT_FROM_CUISINE:
                    continue
                if (d, base) in ctx.skip_cells:
                    continue
                pool = ctx.pools.get(base)
                if pool is None or len(pool) == 0:
                    continue
                if cuisine_col not in pool.columns:
                    continue
                cuisines = pool[cuisine_col].map(_norm_str)
                south_total += int((cuisines == south_val).sum())
                north_total += int((cuisines == north_val).sum())

            for label, count, target_val in (
                ('south_indian', south_total, south_val),
                ('north_indian', north_total, north_val),
            ):
                if count == 0:
                    diags.append(Diagnostic(
                        rule=self.name,
                        rule_type=self.rule_type.value,
                        severity=DiagnosticSeverity.ERROR,
                        phase=DiagnosticPhase.APPLY,
                        message=(
                            f"Mix theme on {day_label} requires ≥1 "
                            f"{label} item across non-exempt slots, "
                            f"but the pools have 0."
                        ),
                        suggestion=(
                            f"Add at least one {label} item to a "
                            f"non-exempt slot, or change {day_label}'s "
                            f"theme in the customisation editor."
                        ),
                        affected={
                            'date': d.isoformat(),
                            'day_type': 'mix',
                            'cuisine': target_val,
                            'count': 0,
                        },
                    ))
                elif count == 1:
                    diags.append(Diagnostic(
                        rule=self.name,
                        rule_type=self.rule_type.value,
                        severity=DiagnosticSeverity.WARNING,
                        phase=DiagnosticPhase.APPLY,
                        message=(
                            f"Mix theme on {day_label}: only 1 {label} "
                            f"item available across non-exempt slots; "
                            f"any cooldown / theme filter that drops it "
                            f"will make this day infeasible."
                        ),
                        suggestion=f"Add more {label} items to the ontology.",
                        affected={
                            'date': d.isoformat(),
                            'day_type': 'mix',
                            'cuisine': target_val,
                            'count': 1,
                        },
                    ))
        return diags


# ---------------------------------------------------------------------------
# ThemeSlotFilterRule
# ---------------------------------------------------------------------------

# Slots that get Chinese-specific filtering
_CHINESE_FLAG_MAP = {
    'rice': 'is_chinese_fried_rice',
    'veg_gravy': 'is_chinese_veg_gravy',
    'nonveg_main': 'is_chinese_chicken_gravy',
}

# Biryani flag map
_BIRYANI_FLAG_MAP = {
    'rice': 'is_mixedveg_biryani',
    'nonveg_main': 'is_nonveg_biryani',
}

# Continental flag map — mirrors the Chinese map but keyed off the
# ``is_continental_*`` columns in the ontology.
# Note: veg_dry is intentionally absent — on a continental day the continental
# veg is served as the GRAVY, and the veg_dry slot stays a normal (Indian)
# dish. So veg_dry is never narrowed to continental.
_CONTINENTAL_FLAG_MAP = {
    'rice': 'is_continental_carb',
    'veg_gravy': 'is_continental_veg_gravy',
    'nonveg_main': 'is_continental_chicken_gravy',
    'starter': 'is_continental_starter',
}


# Slots where a Chinese / Continental item is a "main" menu dish. Cuisine
# exclusivity confines those cuisines to their own theme day ONLY for these
# slots; universal slots (soup, salad, welcome_drink, dal, …) keep their
# incidentally-tagged continental items on any day so their variety isn't
# gutted (e.g. most salads are tagged continental). Listed explicitly (not
# derived from the flag maps) so veg_dry stays covered even though it is
# deliberately excluded from _CONTINENTAL_FLAG_MAP.
_CUISINE_MAIN_SLOTS = {'rice', 'veg_gravy', 'veg_dry', 'starter', 'nonveg_main'}

# North/South chicken gravies are the "always-allowed" nonveg gravy on a
# two-nonveg counter: the slot_composition rule pairs one themed nonveg (biryani
# / chinese / dry) with one of these. On chinese / biryani / cuisine days the
# theme filter would otherwise strip them from nonveg_main, so we union them
# back in — but ONLY when the counter actually serves two nonveg mains.
_NONVEG_REGIONAL_GRAVY_FLAGS = ('is_north_chicken_gravy', 'is_south_chicken_gravy')


# Dish families a larger non-veg station composes beyond the themed dish and the
# regional gravy. Kept in the pool for counters that serve enough dishes to need
# them (see _augment_nonveg_pair).
_NONVEG_STRUCTURAL_FLAGS = (
    'is_nonveg_dry', 'is_tandoor', 'is_tandoor_nonveg_dry', 'is_egg_dish',
)


def _nonveg_slot_count(cfg) -> int:
    counts = getattr(cfg, 'slot_counts', None) or {}
    try:
        return int(counts.get('nonveg_main', 1) or 1)
    except (TypeError, ValueError):
        return 1


def _has_multi_nonveg(cfg) -> bool:
    """True when the counter serves 2+ ``nonveg_main`` dishes (so the day's
    nonveg pair needs a themed dish + a regional gravy)."""
    return _nonveg_slot_count(cfg) >= 2


def _nonveg_regional_gravy_mask(pool: pd.DataFrame) -> pd.Series:
    mask = pd.Series(False, index=pool.index)
    for col in _NONVEG_REGIONAL_GRAVY_FLAGS:
        if col in pool.columns:
            mask = mask | (pool[col].map(_to_bool01) == 1)
    return mask


def _chinese_side_mask(pool: pd.DataFrame) -> pd.Series:
    """Detect Chinese-appropriate veg_dry items via text heuristics."""
    text = (pool['item'].astype(str) + ' ' +
            pool.get('sub_category', pd.Series('', index=pool.index)).astype(str))
    text = text.str.lower()
    return (
        text.str.contains('chinese', na=False) |
        text.str.contains('manchurian', na=False) |
        text.str.contains('schezwan', na=False) |
        text.str.contains('szechuan', na=False) |
        text.str.contains('gobi_65', na=False) |
        text.str.contains('gobi 65', na=False) |
        text.str.contains('baby_corn', na=False) |
        text.str.contains('baby corn', na=False) |
        text.str.contains('noodle', na=False) |
        text.str.contains('chilli', na=False)
    )


class ThemeSlotFilterRule(BaseMenuRule):
    """
    Config:
    {
        "type": "theme_slot_filter",
        "name": "theme_cuisine_filter",
        "exempt_slots": ["welcome_drink", "dal", "sambar", "rasam",
                         "starter", "soup", "salad", "healthy_rice"]
    }
    """

    def __init__(self, rule_config: Dict[str, Any]):
        super().__init__(rule_config)
        self.rule_type = MenuRuleType.THEME_SLOT_FILTER
        # Always honour the canonical cuisine-exempt set (dal/rasam/curd_rice/
        # combination slots, etc.) even if the JSON config lists a narrower
        # set — the config can only ADD exemptions, never drop a canonical one.
        exempt = rule_config.get('exempt_slots')
        self.exempt_slots: Set[str] = (
            set(exempt) | set(EXEMPT_FROM_CUISINE) if exempt
            else set(EXEMPT_FROM_CUISINE)
        )

    def pre_filter_pool(self, pool: pd.DataFrame, date: dt.date,
                        base_slot: str, day_type: str,
                        filter_context: Dict[str, Any]) -> pd.DataFrame:
        if len(pool) == 0:
            return pool

        # Cuisine exclusivity: Chinese / Continental main dishes appear ONLY on
        # their own theme day. Applied before the day-specific narrowing.
        pool = self._exclude_offtheme_cuisines(pool, base_slot, day_type)
        if len(pool) == 0:
            return pool

        cfg = filter_context.get('cfg')

        if day_type == 'chinese':
            return self._filter_chinese(pool, base_slot, cfg)
        if day_type == 'continental':
            return self._filter_by_flag_map(pool, base_slot, _CONTINENTAL_FLAG_MAP)
        if day_type == 'biryani':
            return self._filter_biryani(pool, base_slot, cfg)
        if day_type in ('south', 'north'):
            return self._filter_cuisine(pool, base_slot, day_type, cfg)
        # 'mix', 'holiday', 'normal' — no theme filtering
        return pool

    def _exclude_offtheme_cuisines(self, pool: pd.DataFrame, base_slot: str,
                                   day_type: str) -> pd.DataFrame:
        """Drop Chinese / Continental dishes on days that aren't their theme,
        for cuisine-main slots only. `chinese_continental` is already resolved
        to `chinese` or `continental` by the time day_type reaches here, so an
        odd-week continental day keeps continental and drops chinese, etc.

        Falls back to the unfiltered pool if the exclusion would empty the slot,
        so a thin client pool can't be forced INFEASIBLE by this rule.
        """
        if base_slot not in _CUISINE_MAIN_SLOTS or 'cuisine_family' not in pool.columns:
            return pool
        cf = pool['cuisine_family'].astype(str).str.strip().str.lower()
        drop = pd.Series(False, index=pool.index)
        # Chinese dishes only on chinese days.
        if day_type != 'chinese':
            drop = drop | (cf == 'chinese')
        # Continental dishes only on continental days — AND never in veg_dry:
        # on a continental day the continental veg is the gravy, and the veg_dry
        # slot stays a normal (Indian) dish. So one continental veg + one
        # normal veg, with continental defaulting to the gravy.
        if day_type != 'continental' or base_slot == 'veg_dry':
            drop = drop | (cf == 'continental')
        kept = pool[~drop]
        return kept if len(kept) > 0 else pool

    def _augment_nonveg_pair(self, pool: pd.DataFrame, base_slot: str,
                             filtered: pd.DataFrame, cfg) -> pd.DataFrame:
        """Keep a multi-dish non-veg counter's non-themed dish families.

        On a two-nonveg counter, keep the day's themed ``nonveg_main`` dishes
        PLUS the always-allowed north/south chicken gravies, so the
        ``slot_composition`` rule can place one themed dish + one regional gravy.
        A single-nonveg counter is returned unchanged.

        A counter serving 3+ also keeps the structural families a bigger
        composition places — dry, kebab/tandoor and egg. The filter's job is to
        guarantee the *themed* dish is available, not to make every dish on the
        counter themed: narrowing a 5-dish station to biryani + chicken gravy
        left it 0 dry and 2 egg items against a composition wanting one of each
        every day, which is unsatisfiable however the solver picks. The themed
        dish is still guaranteed — the composition rule mandates it.
        """
        if base_slot != 'nonveg_main' or not _has_multi_nonveg(cfg):
            return filtered
        keep = _nonveg_regional_gravy_mask(pool)
        if _nonveg_slot_count(cfg) >= 3:
            for col in _NONVEG_STRUCTURAL_FLAGS:
                if col in pool.columns:
                    keep = keep | (pool[col].map(_to_bool01) == 1)
        extra = pool[keep]
        if len(extra) == 0:
            return filtered
        return pool.loc[filtered.index.union(extra.index)]

    def _filter_chinese(self, pool: pd.DataFrame, base_slot: str, cfg) -> pd.DataFrame:
        flag_col = _CHINESE_FLAG_MAP.get(base_slot)
        if flag_col and flag_col in pool.columns:
            filtered = pool[pool[flag_col].map(_to_bool01) == 1]
            if len(filtered) > 0:
                return self._augment_nonveg_pair(pool, base_slot, filtered, cfg)

        if base_slot == 'veg_dry':
            mask = _chinese_side_mask(pool)
            filtered = pool[mask]
            if len(filtered) > 0:
                return filtered

        # Exempt slots and slots without flags: return unfiltered
        return pool

    def _filter_by_flag_map(self, pool: pd.DataFrame, base_slot: str,
                            flag_map: Dict[str, str]) -> pd.DataFrame:
        """Narrow *pool* to items whose theme flag (from *flag_map*) is set.

        Falls back to the unfiltered pool when the flag matches nothing so the
        day stays feasible (same contract as the Chinese/biryani filters).
        """
        flag_col = flag_map.get(base_slot)
        if flag_col and flag_col in pool.columns:
            filtered = pool[pool[flag_col].map(_to_bool01) == 1]
            if len(filtered) > 0:
                return filtered
        return pool

    def _filter_biryani(self, pool: pd.DataFrame, base_slot: str, cfg) -> pd.DataFrame:
        flag_col = _BIRYANI_FLAG_MAP.get(base_slot)
        if flag_col and flag_col in pool.columns:
            filtered = pool[pool[flag_col].map(_to_bool01) == 1]
            if len(filtered) > 0:
                return self._augment_nonveg_pair(pool, base_slot, filtered, cfg)
        return pool

    def _filter_cuisine(self, pool: pd.DataFrame, base_slot: str,
                        day_type: str, cfg) -> pd.DataFrame:
        cuisine_col = cfg.cuisine_col if cfg else 'cuisine_family'
        south_val = cfg.cuisine_south_value if cfg else 'south_indian'
        north_val = cfg.cuisine_north_value if cfg else 'north_indian'

        target = south_val if day_type == 'south' else north_val

        # Bread cuisine lock: south bread on south days, non-south on others.
        # `exempt_slots` wins when it names bread — the lock used to run ahead of
        # the exemption check below and could not be switched off at all, so a
        # ruleset listing `bread` was silently ignored. Chennai needs it off: its
        # non-dosai breads are the wheat flatbreads a Tamil lunch actually serves
        # alongside the rice, and locking bread to south_indian on a south day
        # narrowed the slot to the dosai/idly family.
        if base_slot == 'bread' and base_slot not in self.exempt_slots:
            if cuisine_col in pool.columns:
                if day_type == 'south':
                    filtered = pool[pool[cuisine_col].map(_norm_str) == south_val]
                else:
                    filtered = pool[pool[cuisine_col].map(_norm_str) != south_val]
                if len(filtered) > 0:
                    return filtered
            return pool

        # Exempt slots: no cuisine filtering
        if base_slot in self.exempt_slots:
            return pool

        # Non-exempt slots: filter by matching cuisine_family
        if cuisine_col in pool.columns:
            filtered = pool[pool[cuisine_col].map(_norm_str) == target]
            if len(filtered) > 0:
                return self._augment_nonveg_pair(pool, base_slot, filtered, cfg)

        return pool

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        pass  # All filtering happens in pre_filter_pool

    def diagnose(self, ctx: DiagnoseContext) -> List[Diagnostic]:
        """Project the theme slot filter for every (date, slot) on a
        themed day and report:

          - WARNING when the configured flag column doesn't match any
            items at all (filter would empty the pool; the rule itself
            falls back to unfiltered, so the user gets a non-theme
            menu silently — surfacing this lets them fix the data).
          - INFO   when the filter narrows the pool by ≥50%, aggregated to
            one entry per slot rather than one per (date, slot).

        The narrowing INFO is emitted **per slot, not per day**. Narrowing is
        this rule's whole job — every themed day narrows every cuisine-main
        slot — so the per-day form produced 706 entries across the client base,
        each carrying the suggestion "No action needed", and buried the handful
        of real warnings operators need to see. One line per slot keeps the
        same information (day count and the resulting range) at 1/5 the volume.

        Never ERROR: this rule's design is to fall back to the
        unfiltered pool when filtering would empty it, so it can't be
        the *cause* of an infeasibility on its own. (The downstream
        cuisine/coupling/item_cooldown rules emit their own errors
        based on the data the user actually has.)
        """
        diags: List[Diagnostic] = []
        # slot -> {'days': [...], 'before': set(), 'after': [...], 'themes': set()}
        narrowed: Dict[str, Dict[str, Any]] = {}
        cfg = ctx.cfg
        cuisine_col = cfg.cuisine_col if cfg else 'cuisine_family'
        south_val = cfg.cuisine_south_value if cfg else 'south_indian'
        north_val = cfg.cuisine_north_value if cfg else 'north_indian'

        base_slots = ctx.active_base_slots or list(BASE_SLOT_NAMES)

        for d in ctx.dates:
            day_type = ctx.day_types.get(d, '')
            if day_type not in ('chinese', 'continental', 'biryani', 'south', 'north'):
                continue
            day_label = d.strftime('%A %d %b')

            for base in base_slots:
                if (d, base) in ctx.skip_cells:
                    continue
                # No `and base != 'bread'` here any more: the bread cuisine lock
                # now honours the exemption, so diagnose() must agree with
                # pre_filter_pool() or it reports narrowing that never happens.
                if base in self.exempt_slots:
                    continue
                pool = ctx.pools.get(base)
                if pool is None or len(pool) == 0:
                    continue

                filtered_size = self._project_filter_size(
                    pool, base, day_type, cuisine_col, south_val, north_val,
                )
                if filtered_size is None:
                    continue  # No filter applies to this (slot, day_type)
                slot_label = base.replace('_', ' ')

                if filtered_size == 0:
                    diags.append(Diagnostic(
                        rule=self.name,
                        rule_type=self.rule_type.value,
                        severity=DiagnosticSeverity.WARNING,
                        phase=DiagnosticPhase.PRE_FILTER,
                        message=(
                            f"{day_type.capitalize()} {day_label}: 0 items "
                            f"match the {day_type} filter for the "
                            f"{slot_label} slot. Falling back to the "
                            f"unfiltered pool — the plan will use a "
                            f"non-{day_type} item here."
                        ),
                        suggestion=(
                            f"Tag at least one {slot_label} item as "
                            f"{day_type} in the ontology, or accept "
                            f"the non-theme fallback."
                        ),
                        affected={
                            'date': d.isoformat(),
                            'slot': base,
                            'day_type': day_type,
                            'pool_size_before': len(pool),
                            'pool_size_after': 0,
                        },
                    ))
                elif filtered_size < len(pool) // 2:
                    entry = narrowed.setdefault(base, {
                        'days': [], 'themes': set(), 'before': len(pool),
                        'after': [],
                    })
                    entry['days'].append(d.isoformat())
                    entry['themes'].add(day_type)
                    entry['after'].append(filtered_size)

        for base, entry in sorted(narrowed.items()):
            slot_label = base.replace('_', ' ')
            after = entry['after']
            span = (
                f"{min(after)} items"
                if min(after) == max(after)
                else f"{min(after)}-{max(after)} items"
            )
            diags.append(Diagnostic(
                rule=self.name,
                rule_type=self.rule_type.value,
                severity=DiagnosticSeverity.INFO,
                phase=DiagnosticPhase.PRE_FILTER,
                message=(
                    f"Theme filter narrowed the {slot_label} pool on "
                    f"{len(entry['days'])} day(s) "
                    f"({', '.join(sorted(entry['themes']))}): "
                    f"{entry['before']} → {span}."
                ),
                suggestion="No action needed — this is the theme filter working.",
                affected={
                    'slot': base,
                    'dates': entry['days'],
                    'day_types': sorted(entry['themes']),
                    'pool_size_before': entry['before'],
                    'pool_size_after_min': min(after),
                    'pool_size_after_max': max(after),
                },
            ))
        return diags

    def _project_filter_size(
        self,
        pool: pd.DataFrame,
        base_slot: str,
        day_type: str,
        cuisine_col: str,
        south_val: str,
        north_val: str,
    ):
        """Return the post-filter pool size for *(base_slot, day_type)*
        WITHOUT applying the rule's fallback-to-unfiltered behaviour.

        Returns ``None`` when no filter applies to this combination so
        the caller can skip it.
        """
        if day_type == 'chinese':
            flag_col = _CHINESE_FLAG_MAP.get(base_slot)
            if flag_col and flag_col in pool.columns:
                return int((pool[flag_col].map(_to_bool01) == 1).sum())
            if base_slot == 'veg_dry':
                return int(_chinese_side_mask(pool).sum())
            return None

        if day_type == 'continental':
            flag_col = _CONTINENTAL_FLAG_MAP.get(base_slot)
            if flag_col and flag_col in pool.columns:
                return int((pool[flag_col].map(_to_bool01) == 1).sum())
            return None

        if day_type == 'biryani':
            flag_col = _BIRYANI_FLAG_MAP.get(base_slot)
            if flag_col and flag_col in pool.columns:
                return int((pool[flag_col].map(_to_bool01) == 1).sum())
            return None

        # south / north
        if (base_slot == 'bread' and base_slot not in self.exempt_slots
                and cuisine_col in pool.columns):
            cuisines = pool[cuisine_col].map(_norm_str)
            if day_type == 'south':
                return int((cuisines == south_val).sum())
            return int((cuisines != south_val).sum())

        if base_slot in self.exempt_slots:
            return None  # No cuisine filter on an exempt slot, bread included

        if cuisine_col not in pool.columns:
            return None
        target = south_val if day_type == 'south' else north_val
        return int((pool[cuisine_col].map(_norm_str) == target).sum())


# ---------------------------------------------------------------------------
# ThemeStarterPreferenceRule
# ---------------------------------------------------------------------------


class ThemeStarterPreferenceRule(BaseMenuRule):
    """
    Config:
    {
        "type": "theme_starter_preference",
        "name": "prefer_theme_starters",
        "bonus_weight": 1000000
    }
    """

    severity = MenuRuleSeverity.SOFT

    def __init__(self, rule_config: Dict[str, Any]):
        super().__init__(rule_config)
        self.rule_type = MenuRuleType.THEME_STARTER_PREFERENCE
        self.bonus_weight = rule_config.get('bonus_weight', 1000000)

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        pass  # This rule contributes to objective only

    def get_objective_terms(self, model: cp_model.CpModel,
                            context: Dict[str, Any]) -> List:
        cells = context.get('cells', [])
        dates = context.get('dates', [])
        find_cells = context.get('find_cells_fn')
        link_any = context.get('link_any_fn')
        cfg = context.get('cfg')

        if not find_cells or not link_any or not cfg or not cfg.prefer_theme_starter:
            return []

        ok_vars = []
        for di in range(len(dates)):
            for idx, scell in enumerate(find_cells(cells, di, 'starter'), start=1):
                lits = [v for v, pref in zip(scell.x_vars, scell.theme_pref_flags) if pref]
                if lits:
                    ok = model.NewBoolVar(f'starter_theme_ok_{di}_{idx}')
                    link_any(model, lits, ok)
                    ok_vars.append(ok)

        if ok_vars:
            return [sum(ok_vars) * self.bonus_weight]
        return []


# ---------------------------------------------------------------------------
# ThemeFallbackPenaltyRule
# ---------------------------------------------------------------------------


class ThemeFallbackPenaltyRule(BaseMenuRule):
    """
    Config:
    {
        "type": "theme_fallback_penalty",
        "name": "penalize_non_theme_fallback",
        "penalty": 2000000
    }
    """

    severity = MenuRuleSeverity.SOFT

    def __init__(self, rule_config: Dict[str, Any]):
        super().__init__(rule_config)
        self.rule_type = MenuRuleType.THEME_FALLBACK_PENALTY
        self.penalty = rule_config.get('penalty', 2000000)

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        return

    def get_objective_terms(self, model: cp_model.CpModel,
                            context: Dict[str, Any]) -> List:
        fallback_bools = context.get('theme_fallback_bools') or []
        if not fallback_bools:
            return []
        return [sum(fallback_bools) * (-abs(int(self.penalty)))]
