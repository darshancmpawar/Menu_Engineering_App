"""Generic per-day slot-composition rule (Phase-3 rule-type framework).

Constrains *how a slot family is composed on a single day* — e.g. "of the two
``nonveg_main`` dishes today, one is a dry and one is a north/south chicken
gravy" — and lets that composition switch on the day's theme (biryani day → one
biryani + one gravy; chinese day → one chinese nonveg + one gravy; every other
theme → one dry + one gravy).

This is the piece the other rule types don't cover: ``selector_frequency`` counts
matches across the *horizon* and ``attribute_grouping`` constrains values *within
a slot's candidates*, but neither pins the per-day mix of two co-located slots.

Config::

    {
        "type": "slot_composition",
        "name": "nonveg_main_daily_pair",
        "base_slot": "nonveg_main",
        "requires_slot_count": 2,          # only active when the day has exactly
                                           # this many expanded slots (self-gate;
                                           # omit = apply to whatever exists)
        "components": [                    # default mix (used when no theme match)
            {"selector": {"flag": "is_nonveg_dry"}, "count": 1},
            {"selector": {"any_flag": ["is_north_chicken_gravy",
                                       "is_south_chicken_gravy"]}, "count": 1}
        ],
        "components_by_theme": {           # optional per-theme overrides
            "chinese": [ ... ],
            "biryani": [ ... ]
        }
    }

Each *component* is ``{selector, count}`` using the same selector grammar as
``selector_frequency`` (flag / any_flag / sub_category / item / key_ingredient /
primary_protein / course_type / cuisine_family). For a given day the rule adds,
per component, ``sum(matching candidate vars) >= count``.

The ``>=`` (not ``==``) is deliberate: when the components exactly partition the
slots (e.g. two slots, two ``count: 1`` components) each lower bound is forced to
equality anyway — "≥1 dry AND ≥1 gravy" across two cells *is* exactly one of
each — but if one component's pool is empty its bound simply drops, and the
surviving component never becomes unsatisfiable by being pinned to an impossible
exact count. So it reads as an exact composition when the pool is rich and
relaxes to best-effort when it isn't.

**Auto-relax**: ``count`` is also capped to how many matching candidates the
day's pool actually holds, so a thin/absent pool relaxes the component instead of
forcing an INFEASIBLE model (same contract as ``selector_frequency``).
"""

import logging
from typing import Dict, Any, List, Optional, Tuple

from ortools.sat.python import cp_model

from .base_menu_rule import (
    BaseMenuRule,
    Diagnostic,
    DiagnoseContext,
    DiagnosticPhase,
    DiagnosticSeverity,
    MenuRuleType,
)
from src.constants import repeatable_row
from .selector_frequency_rule import SelectorFrequencyRule
from .slot_day_restriction_rule import _WEEKDAY_TOKENS
from .unique_items_menu_rule import matches_declared

logger = logging.getLogger(__name__)

# A parsed component: (matcher tuple, required count).
_Component = Tuple[Any, int]


def _component_matches(row, matcher) -> bool:
    """Match *row* against a component matcher, honouring ``exclude``.

    A component may carry an ``exclude`` selector, same grammar as its
    ``selector`` — needed because the ontology's flags are not always clean:
    ``egg_drumstick_curry`` and ``egg_kurma`` carry ``is_south_chicken_gravy``
    despite being egg dishes, so "a chicken gravy on Monday" would happily be
    satisfied by an egg curry. Excluding ``is_egg_dish`` states the intent
    precisely without waiting on a data fix.
    """
    kind, val = matcher
    if kind == '_and_not':
        include, exclude = val
        return (SelectorFrequencyRule._matches(row, include)
                and not SelectorFrequencyRule._matches(row, exclude))
    return SelectorFrequencyRule._matches(row, matcher)


def _matcher_key(matcher) -> Tuple[str, str]:
    """Hashable identity for a matcher (``any_flag`` carries a list)."""
    kind, val = matcher
    if kind == '_and_not':
        include, exclude = val
        return (kind, f"{_matcher_key(include)}!{_matcher_key(exclude)}")
    if isinstance(val, (list, tuple)):
        return (kind, '|'.join(sorted(str(v) for v in val)))
    return (kind, str(val))


def _safe(matcher) -> str:
    """A CP-SAT-variable-safe label for a matcher."""
    kind, val = _matcher_key(matcher)
    return f"{kind}_{val}".replace(' ', '_')[:60]


def days_forced_by_composition(peer_rules, ctx, base_slot, row_matches) -> int:
    """How many days a peer composition rule *mandates* an item that
    ``row_matches`` accepts, for ``base_slot``.

    This is the missing half of conflict detection. A frequency cap can be
    contradicted two ways: the pool leaves nothing but matching items (see
    ``SelectorFrequencyRule._forced_days``), or a *composition* rule requires a
    matching item on that day. Siemens Technology's non-veg counter is the second
    kind — its biryani-theme Wednesday and Friday each get a mandatory biryani
    from ``nonveg_main_daily_pair`` while ``nonveg_biryani_once_per_week`` allows
    one biryani day, and neither rule alone can see the contradiction.

    Implication between a component's selector and the caller's is decided from
    the data rather than by comparing selector syntax: the component forces the
    caller's selector on a day when every item the component could satisfy also
    satisfies the caller. That is exact for the identical-selector case and stays
    correct for a narrower component (e.g. "chicken biryani" forcing "biryani").
    """
    comps_by_rule = [
        r for r in (peer_rules or [])
        if isinstance(r, SlotCompositionRule) and r.base_slot == base_slot
    ]
    if not comps_by_rule:
        return 0

    forced = 0
    for d in ctx.dates:
        if (d, base_slot) in (ctx.skip_cells or set()):
            continue
        pool = ctx.pools.get(base_slot)
        if pool is None or not len(pool):
            continue
        day_type = ctx.day_types.get(d, '')
        filter_ctx = {
            'cfg': ctx.cfg, 'banned_by_date': {}, 'ricebread_ban_day': {},
            'pools': ctx.pools, 'slot_num': None,
        }
        for rule in (peer_rules or []):
            pool = rule.pre_filter_pool(pool, d, base_slot, day_type, filter_ctx)
        if not len(pool):
            continue
        rows = [r for _i, r in pool.iterrows()]
        hit = False
        for rule in comps_by_rule:
            for matcher, _count in rule.mandated_components(ctx, day_type, d):
                candidates = [
                    r for r in rows
                    if _component_matches(r, matcher)
                ]
                if candidates and all(row_matches(r) for r in candidates):
                    hit = True
                    break
            if hit:
                break
        if hit:
            forced += 1
    return forced


class SlotCompositionRule(BaseMenuRule):
    def __init__(self, rule_config: Dict[str, Any]):
        super().__init__(rule_config)
        self.rule_type = MenuRuleType.SLOT_COMPOSITION
        self.base_slot: Optional[str] = rule_config.get('base_slot')
        rsc = rule_config.get('requires_slot_count')
        self.requires_slot_count: Optional[int] = int(rsc) if rsc is not None else None
        msc = rule_config.get('min_slot_count')
        self.min_slot_count: Optional[int] = int(msc) if msc is not None else None
        xsc = rule_config.get('max_slot_count')
        self.max_slot_count: Optional[int] = int(xsc) if xsc is not None else None
        self.components: List[_Component] = self._parse_components(
            rule_config.get('components'))
        self.components_by_theme: Dict[str, List[_Component]] = {
            str(theme): self._parse_components(comps)
            for theme, comps in (rule_config.get('components_by_theme') or {}).items()
        }
        # Per-weekday override, checked BEFORE the theme map. Several clients pin
        # a dish family to a named weekday rather than to a theme — Infenion's
        # non-veg row is "Monday chicken gravy, Wednesday egg, Friday biryani,
        # other days blank", which no theme expresses. Keyed by Python weekday
        # index so it lines up with `date.weekday()`. Unrecognised tokens are
        # dropped and reported by validation_errors().
        self.components_by_weekday: Dict[int, List[_Component]] = {}
        self._bad_weekdays: List[str] = []
        for day, comps in (rule_config.get('components_by_weekday') or {}).items():
            idx = _WEEKDAY_TOKENS.get(str(day).strip().lower())
            if idx is None:
                self._bad_weekdays.append(str(day))
                continue
            self.components_by_weekday[idx] = self._parse_components(comps)

    @staticmethod
    def _parse_components(raw) -> List[_Component]:
        """Parse a list of ``{selector, count}`` dicts into matcher tuples.

        Components whose selector doesn't parse are dropped (surfaced by
        :py:meth:`validation_errors`)."""
        out: List[_Component] = []
        for comp in (raw or []):
            if not isinstance(comp, dict):
                continue
            matcher = SelectorFrequencyRule._parse_matcher(comp.get('selector'))
            if matcher is not None and comp.get('exclude'):
                excl = SelectorFrequencyRule._parse_matcher(comp['exclude'])
                if excl is None:
                    matcher = None      # bad exclude -> surfaced by validation
                else:
                    matcher = ('_and_not', (matcher, excl))
            count = comp.get('count', 1)
            try:
                count = int(count)
            except (TypeError, ValueError):
                count = None
            if matcher is not None and count is not None and count >= 1:
                out.append((matcher, count))
        return out

    def _all_component_lists(self) -> List[List[_Component]]:
        return ([self.components] + list(self.components_by_theme.values())
                + list(self.components_by_weekday.values()))

    def _gate_allows(self, configured: int) -> bool:
        """Does a counter serving *configured* of this slot get composed?

        ``min_slot_count`` is the form to prefer. ``requires_slot_count`` demands
        an *exact* match, which silently excluded every counter that serves more
        than the stated number: the base ruleset asked for exactly 2
        ``nonveg_main``, so Siemens Technology's 3-dish non-veg counter got no
        composition at all and its biryani-theme days came back with no biryani
        while non-biryani days got two. Exact matching is kept for configs that
        rely on it, but a range is what "compose the family" actually means.
        """
        if self.min_slot_count is not None or self.max_slot_count is not None:
            if self.min_slot_count is not None and configured < self.min_slot_count:
                return False
            if self.max_slot_count is not None and configured > self.max_slot_count:
                return False
            return True
        if self.requires_slot_count is not None:
            return configured == self.requires_slot_count
        return True

    def validate_config(self) -> bool:
        return not self.validation_errors()

    def validation_errors(self) -> List[str]:
        errs: List[str] = []
        if not self.base_slot:
            errs.append("base_slot is required")
        lists = self._all_component_lists()
        if not any(lists):
            errs.append("at least one component (in 'components' or "
                        "'components_by_theme') with a valid selector and count >= 1")
        # Every raw component that survived parsing already has count >= 1; a
        # configured component that produced nothing means a bad selector/count.
        raw_total = len(self.config.get('components') or [])
        raw_total += sum(len(v or []) for v in (self.config.get('components_by_theme') or {}).values())
        raw_total += sum(len(v or []) for v in (self.config.get('components_by_weekday') or {}).values())
        parsed_total = sum(len(lst) for lst in lists)
        if raw_total and parsed_total < raw_total:
            errs.append("every component needs a valid selector and integer count >= 1")
        if self.requires_slot_count is not None and self.requires_slot_count < 1:
            errs.append(f"requires_slot_count must be >= 1 (got {self.requires_slot_count})")
        if self.min_slot_count is not None and self.min_slot_count < 1:
            errs.append(f"min_slot_count must be >= 1 (got {self.min_slot_count})")
        if self._bad_weekdays:
            errs.append(
                f"components_by_weekday has unrecognised weekday(s): "
                f"{sorted(self._bad_weekdays)}"
            )
        if self.max_slot_count is not None and self.max_slot_count < 1:
            errs.append(f"max_slot_count must be >= 1 (got {self.max_slot_count})")
        if (self.min_slot_count is not None and self.max_slot_count is not None
                and self.min_slot_count > self.max_slot_count):
            errs.append(
                f"min_slot_count ({self.min_slot_count}) must be <= "
                f"max_slot_count ({self.max_slot_count})"
            )
        if self.requires_slot_count is not None and (
                self.min_slot_count is not None
                or self.max_slot_count is not None):
            errs.append(
                "set either min_slot_count/max_slot_count or "
                "requires_slot_count, not both"
            )
        return errs

    def _components_for(self, date, day_type: str) -> List[_Component]:
        """Components for one day: weekday override first, then theme, then default.

        Weekday wins because it is the more specific statement — a client saying
        "Friday biryani" means Friday regardless of what theme Friday carries. A
        weekday configured with an empty list composes nothing that day, which is
        how "other days blank" is expressed.
        """
        if date is not None and self.components_by_weekday:
            idx = date.weekday()
            if idx in self.components_by_weekday:
                return self.components_by_weekday[idx]
        return self.components_by_theme.get(day_type, self.components)

    def mandated_components(self, ctx, day_type: str, date=None) -> List[_Component]:
        """Components this rule will require on a day of *day_type*.

        Empty when the counter's slot count leaves the rule inactive, so a
        caller reasoning about conflicts sees the same gate ``apply()`` uses.
        """
        if not self.base_slot:
            return []
        slot_counts = (
            ctx.client_cfg.slot_counts if ctx.client_cfg is not None else {}
        ) or {}
        configured = int(slot_counts.get(self.base_slot, 1) or 1)
        if not self._gate_allows(configured):
            return []
        return self._components_for(date, day_type)

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        cells = context.get('cells', [])
        dates = context.get('dates', [])
        day_types = context.get('day_types', [])
        if not cells or not self.base_slot:
            return

        # Which components cannot be required on every applicable day, because
        # the horizon does not hold enough DISTINCT matching items to satisfy
        # them under unique_items. Per-day availability is not the binding
        # constraint here: L&T's 5-dish non-veg station has a kebab candidate
        # every day, but only ONE distinct kebab in its pool, so "a kebab daily"
        # over five days is arithmetically impossible however the solver picks.
        # Those components get a horizon-level floor of what the pool can supply
        # instead of an impossible per-day mandate.
        limited = self._horizon_limited_components(cells, dates, day_types, context)

        for di in range(len(dates)):
            day_cells = [
                c for c in cells
                if c.d_idx == di and c.base_slot == self.base_slot
            ]
            if not day_cells:
                continue
            # Self-gate: only compose when the *counter* is configured with the
            # expected number of this slot (leaves single-slot counters
            # untouched).
            #
            # Gate on the configured slot count, not on len(day_cells): a client
            # constant that pins one expansion (e.g. nonveg_main__2 = "boiled
            # egg") removes that cell, and gating on surviving cells silently
            # switched the whole composition rule off for that day — Plan View
            # pins nonveg_main__2 every day, which disabled the nonveg pairing
            # for the entire week with no warning. Components are already capped
            # to what the surviving cells can supply just below, so composing
            # against a partially-pinned family degrades instead of vanishing.
            if self.requires_slot_count is not None or self.min_slot_count is not None:
                cfg = context.get('cfg')
                slot_counts = getattr(cfg, 'slot_counts', None) or {}
                configured = int(slot_counts.get(self.base_slot, len(day_cells)))
                if not self._gate_allows(configured):
                    continue

            theme = day_types[di] if di < len(day_types) else ''
            comps = self._components_for(dates[di], theme)
            if not comps:
                continue

            # Components are capped to what this day can actually supply: each
            # to its own candidate count, and collectively to the number of
            # cells left to fill. The cell budget matters when a client constant
            # pins one expansion of the family — two count-1 components against
            # a single surviving cell would demand two different dishes from one
            # slot and make the day INFEASIBLE. Earlier components win the
            # budget, so config order expresses priority.
            budget = len(day_cells)
            for matcher, count in comps:
                if budget <= 0:
                    logger.info(
                        "%s: day %d component %s dropped (no cell left to fill; "
                        "the rest of the family is pinned or restricted)",
                        self.name, di, matcher)
                    continue
                lits = [
                    v for c in day_cells
                    for v, r in zip(c.x_vars, c.cand_rows)
                    if _component_matches(r, matcher)
                ]
                key = _matcher_key(matcher)
                if key in limited:
                    # Horizon-limited: collected below as an at-least-N-days
                    # floor rather than mandated here. Still reserve a cell so a
                    # later component cannot claim the whole family.
                    limited[key]['day_lits'].append((di, lits, count))
                    budget -= min(count, budget)
                    continue
                required = min(count, len(lits), budget)
                if required != count:
                    logger.info(
                        "%s: day %d component %s capped %d -> %d "
                        "(pool/cell limit)",
                        self.name, di, matcher, count, required)
                if required > 0:
                    model.Add(sum(lits) >= required)
                    budget -= required

        self._add_horizon_floors(model, limited)

    def _horizon_limited_components(self, cells, dates, day_types, context):
        """Components whose per-day mandate is arithmetically impossible.

        Returns ``{matcher_key: {matcher, distinct, days, day_lits}}`` for each
        component that applies on more days than the horizon has distinct
        matching items. Uniqueness makes each day's occurrence need its own
        item, so ``distinct`` days is the ceiling on how often it can hold.
        """
        cfg = context.get('cfg')
        slot_counts = getattr(cfg, 'slot_counts', None) or {}
        # Staples declared by a peer rule count too, not just the ontology-wide
        # flags. "Chapati every day" is one distinct item across six days, which
        # reads as a horizon shortfall and degrades the daily mandate to a floor
        # of one — turning "chapati daily" into "chapati once".
        declared = context.get('extra_repeatable') or {}
        out: Dict[Any, Dict[str, Any]] = {}
        seen: Dict[Any, Dict[str, Any]] = {}

        for di in range(len(dates)):
            day_cells = [c for c in cells
                         if c.d_idx == di and c.base_slot == self.base_slot]
            if not day_cells:
                continue
            if self.requires_slot_count is not None or self.min_slot_count is not None \
                    or self.max_slot_count is not None:
                configured = int(slot_counts.get(self.base_slot, len(day_cells)))
                if not self._gate_allows(configured):
                    continue
            theme = day_types[di] if di < len(day_types) else ''
            for matcher, count in self._components_for(dates[di], theme):
                key = _matcher_key(matcher)
                entry = seen.setdefault(
                    key, {'matcher': matcher, 'days': 0, 'need': 0,
                          'items': set(), 'day_lits': [], 'staple': False})
                entry['days'] += 1
                entry['need'] += count
                for c in day_cells:
                    for r in c.cand_rows:
                        if _component_matches(r, matcher):
                            if (repeatable_row(r, self.base_slot)
                                    or matches_declared(
                                        r, self.base_slot, declared)):
                                # A staple satisfies the component on every day
                                # by itself, so distinct count is irrelevant.
                                entry['staple'] = True
                                continue
                            name = str(r.get('item', '')).strip().lower()
                            if name:
                                entry['items'].add(name)

        for key, entry in seen.items():
            if entry['staple']:
                continue
            distinct = len(entry['items'])
            if distinct and distinct < entry['need']:
                logger.info(
                    "%s: component %s needs %d occurrence(s) across %d day(s) "
                    "but the pool holds %d distinct matching item(s); enforcing "
                    "it on %d day(s) instead of every day",
                    self.name, entry['matcher'], entry['need'], entry['days'],
                    distinct, distinct)
                entry['distinct'] = distinct
                out[key] = entry
        return out

    def _add_horizon_floors(self, model, limited) -> None:
        """For each horizon-limited component, require it on as many days as the
        pool can actually supply — the maximum achievable, not an arbitrary
        subset and not nothing."""
        for entry in limited.values():
            day_lits = [(di, lits, count) for di, lits, count in entry['day_lits']
                        if lits]
            if not day_lits:
                continue
            indicators = []
            for di, lits, count in day_lits:
                b = model.NewBoolVar(f'{self.name}_hz_{_safe(entry["matcher"])}_{di}')
                model.Add(sum(lits) >= count).OnlyEnforceIf(b)
                indicators.append(b)
            floor = min(entry['distinct'], len(indicators))
            if floor > 0:
                model.Add(sum(indicators) >= floor)

    # Populated by the diagnostics aggregator (see diagnostics.run_diagnostics).
    _peer_rules: List[Any] = []

    def diagnose(self, ctx: DiagnoseContext) -> List[Diagnostic]:
        """Report when a day's composition cannot be assembled as configured.

        Two silent failure modes, both WARNING because ``apply()`` caps each
        component to what the day can supply rather than failing:

        * the counter is not configured with ``requires_slot_count`` of this
          slot, so the rule never fires at all — easy to miss when a slot count
          is edited in the UI and a composition rule quietly stops applying;
        * a component's selector matches nothing in the day's pool, so that part
          of the pairing is dropped (a Chinese day with no Chinese dish left
          after the theme filter, for example).
        """
        diags: List[Diagnostic] = []
        if not self.base_slot:
            return diags
        active = ctx.active_base_slots
        if active is not None and self.base_slot not in active:
            return diags

        slot_counts = (
            ctx.client_cfg.slot_counts if ctx.client_cfg is not None else {}
        ) or {}
        configured = int(slot_counts.get(self.base_slot, 1) or 1)
        if not self._gate_allows(configured):
            if self.min_slot_count is not None and self.max_slot_count is not None:
                wanted = f"{self.min_slot_count}-{self.max_slot_count}"
            elif self.min_slot_count is not None:
                wanted = f"at least {self.min_slot_count}"
            elif self.max_slot_count is not None:
                wanted = f"at most {self.max_slot_count}"
            else:
                wanted = f"exactly {self.requires_slot_count}"
            diags.append(Diagnostic(
                rule=self.name, rule_type=self.rule_type.value,
                severity=DiagnosticSeverity.INFO,
                phase=DiagnosticPhase.APPLY,
                message=(
                    f"Composition for '{self.base_slot}' is inactive: it applies "
                    f"to counters serving {wanted} of that slot, and this "
                    f"counter serves {configured}."
                ),
                suggestion=(
                    f"If this counter should be composed, raise its "
                    f"{self.base_slot} count; otherwise no action is needed."
                ),
                affected={
                    'base_slot': self.base_slot,
                    'requires_slot_count': self.requires_slot_count,
                    'min_slot_count': self.min_slot_count,
                    'configured_slot_count': configured,
                },
            ))
            return diags

        if self.base_slot not in ctx.pools:
            return diags

        missing: Dict[str, List[str]] = {}
        for d in ctx.dates:
            if (d, self.base_slot) in (ctx.skip_cells or set()):
                continue
            day_type = ctx.day_types.get(d, '')
            comps = self._components_for(d, day_type)
            if not comps:
                continue
            pool = ctx.pools[self.base_slot]
            filter_ctx = {
                'cfg': ctx.cfg, 'banned_by_date': {}, 'ricebread_ban_day': {},
                'pools': ctx.pools, 'slot_num': None,
            }
            for rule in (self._peer_rules or []):
                pool = rule.pre_filter_pool(
                    pool, d, self.base_slot, day_type, filter_ctx)
            rows = [r for _i, r in pool.iterrows()] if len(pool) else []
            for matcher, count in comps:
                have = sum(
                    1 for r in rows
                    if _component_matches(r, matcher)
                )
                if have < count:
                    label = f"{matcher[0]}={matcher[1]!r}"
                    missing.setdefault(label, []).append(d.isoformat())

        for label, days in sorted(missing.items()):
            diags.append(Diagnostic(
                rule=self.name, rule_type=self.rule_type.value,
                severity=DiagnosticSeverity.WARNING,
                phase=DiagnosticPhase.APPLY,
                message=(
                    f"Composition component {label} for '{self.base_slot}' has "
                    f"too few candidates on {len(days)} day(s), so that part of "
                    f"the pairing is dropped there."
                ),
                suggestion=(
                    "Widen this client's source_pools, add matching items, or "
                    "relax the theme filter on those days if the pairing matters."
                ),
                affected={
                    'base_slot': self.base_slot,
                    'component': label,
                    'days': days,
                },
            ))
        return diags
