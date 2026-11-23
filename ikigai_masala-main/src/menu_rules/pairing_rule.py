"""Pairing rule: one row's dishes follow the dish another row serves that day.

Breakfast accompaniments follow the main (Rippling, owner 18 Nov): idli and
dosa come with a chutney and a sambar, poori with chole or saagu and nothing
else, paratha with curd and a pickle::

    {
        "type": "pairing",
        "name": "breakfast_accompaniments_follow_the_main",
        "when_slot": "breakfast_main",
        "then_slot": "accompaniment",
        "pairs": [
            {"when": {"sub_category": "idly"},
             "then": [{"sub_category": "chutney"}, {"sub_category": "sambar"}]},
            {"when": {"name_contains": ["bature", "kulcha"]},
             "then": [{"name_contains": "chole"}, null]}
        ]
    }

``then`` gives one selector per cell of *then_slot*, in order (``__1``,
``__2`` ...); ``null`` leaves that cell blank on the days the pair applies,
so a row of two serves one or two dishes as the main asks; a cell past the
end of a pair's ``then`` is left free. Blank is allowed only in the
Accompaniments row (``BLANK_ALLOWED_SLOTS``), from a rule whose ``meals`` are
breakfast and/or snacks (``BLANK_ALLOWED_MEALS``); any other ``null`` makes the rule invalid. The first pair
whose ``when`` matches the main is the one that applies, and a main no pair
matches is not served: a pairing table is the list of mains it knows how to
accompany.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from ortools.sat.python import cp_model

from src.constants import BLANK_ALLOWED_MEALS, BLANK_ALLOWED_SLOTS

from .base_menu_rule import BaseMenuRule, MenuRuleType
from .selector_frequency_rule import SelectorFrequencyRule


def _index(slot_id: str) -> int:
    return int(slot_id.partition('__')[2] or 1)


class PairingRule(BaseMenuRule):
    def __init__(self, rule_config: Dict[str, Any]):
        super().__init__(rule_config)
        self.rule_type = MenuRuleType.PAIRING
        self.when_slot: str = rule_config.get('when_slot', '')
        self.then_slot: str = rule_config.get('then_slot', '')
        parse = SelectorFrequencyRule._parse_matcher
        self.pairs: List[tuple] = []
        self._bad = False
        for p in rule_config.get('pairs') or []:
            when = parse(p.get('when') or {})
            raw_then = p.get('then') or []
            then = [None if s is None else parse(s) for s in raw_then]
            # A selector that does not parse must not read as "leave blank".
            if when is None or not then or any(
                    s is None and raw is not None for s, raw in zip(then, raw_then)):
                self._bad = True
            self.pairs.append((when, then))

    def _leaves_blank(self) -> bool:
        return any(sel is None for _, then in self.pairs for sel in then)

    def _blank_allowed(self) -> bool:
        """A blank cell only in the Accompaniments row, and only from a rule
        scoped to breakfast and/or snacks (owner, 18 + 23 Nov)."""
        meals = {str(m).strip().lower() for m in (self.config.get('meals') or [])}
        return self.then_slot in BLANK_ALLOWED_SLOTS and bool(meals) and meals <= BLANK_ALLOWED_MEALS

    def validate_config(self) -> bool:
        return (bool(self.when_slot and self.then_slot and self.pairs) and not self._bad
                and (not self._leaves_blank() or self._blank_allowed()))

    def optional_slot_ids(self) -> Set[str]:
        """The cells of *then_slot* some pair leaves blank: the solver lets them
        hold no dish, and this rule decides, day by day, whether they do."""
        out: Set[str] = set()
        if not self._blank_allowed():
            return out
        for _, then in self.pairs:
            for i, sel in enumerate(then, start=1):
                if sel is None:
                    out.add(f'{self.then_slot}__{i}')
                    if i == 1:
                        out.add(self.then_slot)
        return out

    def _pair_of(self, row) -> Optional[int]:
        return next((k for k, (when, _) in enumerate(self.pairs)
                     if SelectorFrequencyRule._matches(row, when)), None)

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        by_day: Dict[int, Dict[str, list]] = {}
        for c in context.get('cells', []):
            if c.base_slot in (self.when_slot, self.then_slot):
                by_day.setdefault(c.d_idx, {}).setdefault(c.base_slot, []).append(c)
        for day in by_day.values():
            mains, thens = day.get(self.when_slot, []), day.get(self.then_slot, [])
            if not mains:
                continue
            # Which pair the day's main falls under, as one 0/1 sum per pair.
            active: List[list] = [[] for _ in self.pairs]
            for var, row in zip(mains[0].x_vars, mains[0].cand_rows):
                k = self._pair_of(row)
                if k is None:
                    model.Add(var == 0)          # a main the table cannot accompany
                else:
                    active[k].append(var)
            for c in thens:
                i = _index(c.slot_id)
                for (when, then), on in zip(self.pairs, active):
                    if not on or i > len(then):
                        continue                 # a cell the pair does not name is free
                    sel = then[i - 1]
                    if sel is None:
                        model.Add(sum(c.x_vars) <= 1 - sum(on))
                    else:
                        fits = [v for v, r in zip(c.x_vars, c.cand_rows)
                                if SelectorFrequencyRule._matches(r, sel)]
                        model.Add(sum(fits) >= sum(on))
