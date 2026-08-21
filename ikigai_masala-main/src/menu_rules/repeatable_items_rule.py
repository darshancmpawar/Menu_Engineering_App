"""Repeatable-items rule: some dishes in a slot are staples, not variety.

Steamed rice is the obvious case — the same dish every day, and nobody expects
a 20-day gap before it comes back. Which dishes are staples is a *regional*
decision, not a property of the ontology: Pune's rulebook states it outright
(R36, "plain atta phulka/chapathi is allowed on consecutive days") because a
Pune lunch is chapati daily, while a Bangalore bread slot rotating naan,
parathas and rotis wants exactly the no-repeat rule this exempts from::

    {
        "type": "repeatable_items",
        "name": "plain_chapati_may_repeat",
        "base_slot": "bread",
        "selector": {"flag": "is_plain_phulka_chapathi"}
    }

Semantics: matching items in *base_slot* are exempt from ``unique_items`` and
from the item-cooldown history ban. It **permits** repetition — it never forces
it (use ``fixed_daily_item`` for "the same dish every day"), and it never
mandates the dish appear at all.

``scope`` chooses which of the two exemptions applies:

* ``"both"`` (default) — exempt from ``unique_items`` AND the cooldown. The dish
  may recur any day, which is what a staple means (Pune's plain chapati, the
  daily steamed rice).
* ``"cooldown"`` — exempt from the cooldown only; ``unique_items`` still holds,
  so the slot serves distinct dishes within a plan and repeats only once every
  distinct one is used. This is the ``COOLDOWN_EXEMPT_SLOTS`` treatment
  (CLAUDE.md note 11) made available per client instead of globally, and it is
  what a *family* daily needs rather than a single dish: Citrix's welcome drink
  is buttermilk every day and Bangalore carries ten buttermilks — fewer than a
  daily slot needs across a 20-day window, so the ban has to go, but with
  ``"both"`` the solver was free to serve the same one on Monday and Thursday
  while eight others went unused.

Why a rule and not a constant: :data:`src.constants.REPEATABLE_ITEM_FLAGS_BY_SLOT`
is the same declaration global to every city, which is right for the chicken
kebab on a non-veg station and wrong for bread. A rule lives in the city (or
client) ruleset, so the exemption is scoped to whoever asked for it — the same
reason ``fixed_daily_item`` declares its own repeatables rather than growing the
constant.

Both consumers read the declaration through the one hook the solver already
collects (``repeatable_item_flags`` → ``context['extra_repeatable']``), so the
rule that permits a repeat and the rules that forbid one cannot disagree.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ortools.sat.python import cp_model

from .base_menu_rule import (
    BaseMenuRule,
    Diagnostic,
    DiagnoseContext,
    DiagnosticPhase,
    DiagnosticSeverity,
    MenuRuleType,
)
from .selector_frequency_rule import SelectorFrequencyRule

logger = logging.getLogger(__name__)

_SCOPES = frozenset({'both', 'cooldown'})


class RepeatableItemsRule(BaseMenuRule):
    def __init__(self, rule_config: Dict[str, Any]):
        super().__init__(rule_config)
        self.rule_type = MenuRuleType.REPEATABLE_ITEMS
        self.base_slot: Optional[str] = rule_config.get('base_slot')
        self._inc = SelectorFrequencyRule._parse_matcher(rule_config.get('selector'))
        self._exc = SelectorFrequencyRule._parse_matcher(rule_config.get('exclude'))
        self.scope: str = str(rule_config.get('scope', 'both')).strip().lower()

    def validate_config(self) -> bool:
        return not self.validation_errors()

    def validation_errors(self) -> List[str]:
        errs: List[str] = []
        if not self.base_slot:
            errs.append("base_slot is required")
        if self._inc is None:
            errs.append("a valid 'selector' is required")
        if self.scope not in _SCOPES:
            errs.append("scope must be one of " + ", ".join(sorted(_SCOPES)))
        return errs

    def _row_matches(self, row) -> bool:
        return (SelectorFrequencyRule._matches(row, self._inc)
                and not SelectorFrequencyRule._matches(row, self._exc))

    def repeatable_item_flags(self) -> Dict[str, Any]:
        """``{base_slot: matcher}`` — the exemption BOTH consumers honour.

        Collected by ``MenuSolver._declared_repeatable()`` into
        ``context['extra_repeatable']``, which ``unique_items`` folds into its
        repeatable set and ``item_cooldown`` reads before applying history bans.
        Empty under ``scope: "cooldown"``, where only the cooldown stands down.
        """
        if not self.base_slot or self._inc is None or self.scope != 'both':
            return {}
        return {self.base_slot: (self._inc, self._exc)}

    def cooldown_exempt_item_flags(self) -> Dict[str, Any]:
        """``{base_slot: matcher}`` — the exemption ONLY the cooldown honours.

        Read via ``context['extra_cooldown_exempt']`` (and via ``_peer_rules`` in
        ``diagnose()``, which has no context). A separate hook rather than a flag
        on the first one so a consumer that has not been taught about ``scope``
        keeps the narrower behaviour: forgetting to check it leaves the cooldown
        ban in place, which starves a slot visibly, rather than silently
        permitting a repeat the client did not ask for.
        """
        if not self.base_slot or self._inc is None or self.scope != 'cooldown':
            return {}
        return {self.base_slot: (self._inc, self._exc)}

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        # Declarative only: this rule adds no constraints, it removes them from
        # the two rules that read `extra_repeatable`.
        pass

    def diagnose(self, ctx: DiagnoseContext) -> List[Diagnostic]:
        """Report a selector that matches nothing — an exemption that exempts no
        dish silently leaves the slot under the no-repeat rule it was meant to
        release, which is how a starved slot turns into an INFEASIBLE plan."""
        diags: List[Diagnostic] = []
        if not self.base_slot or self._inc is None:
            return diags
        active = ctx.active_base_slots
        if active is not None and self.base_slot not in active:
            return diags
        pool = ctx.pools.get(self.base_slot)
        if pool is None or not len(pool):
            return diags

        matching = sum(1 for _i, r in pool.iterrows() if self._row_matches(r))
        sel = f"{self._inc[0]}={self._inc[1]!r}"
        if matching == 0:
            diags.append(Diagnostic(
                rule=self.name, rule_type=self.rule_type.value,
                severity=DiagnosticSeverity.INFO,
                phase=DiagnosticPhase.PRE_FILTER,
                message=(
                    f"No eligible '{self.base_slot}' item matches {sel}, so this "
                    f"staple exemption applies to nothing and the slot stays "
                    f"fully under unique_items and the item cooldown."
                ),
                suggestion=(
                    "Check the selector against the ontology columns for this "
                    "city's item list, or remove the rule."
                ),
                affected={'base_slot': self.base_slot, 'selector': sel},
            ))
        return diags
