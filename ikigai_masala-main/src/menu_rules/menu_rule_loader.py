"""
Menu rule loader from JSON configuration.
"""

import json
import logging
import os
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# Per-client rules file. Resolved relative to the repo (data/configs) so that
# importing ``src.menu_rules`` never depends on the ``api`` package — the
# ``CLIENT_RULES_CONFIG_PATH`` env var still overrides it. Kept module-level so
# tests can monkeypatch this name.
CLIENT_RULES_CONFIG_PATH = os.getenv(
    'CLIENT_RULES_CONFIG_PATH',
    str(Path(__file__).resolve().parent.parent.parent / 'data' / 'configs' / 'client_rules.json'),
)

# Directory holding one rules file per city (``<city>.json``). A city file may
# ``"extends"`` another city (by bare name) to inherit its rules and override
# by rule ``name``; ``DEFAULT_CITY`` is the reference ruleset and the fallback
# for any city without its own file.
CITY_RULES_DIR = os.getenv(
    'CITY_RULES_DIR',
    str(Path(__file__).resolve().parent.parent.parent / 'data' / 'configs' / 'city_rules'),
)
DEFAULT_CITY = 'bangalore'

from .base_menu_rule import BaseMenuRule
from .cuisine_menu_rule import CuisineMenuRule
from .unique_items_menu_rule import UniqueItemsMenuRule
from .coupling_menu_rule import CouplingMenuRule
from .curd_side_menu_rule import CurdSideMenuRule
from .premium_menu_rule import PremiumMenuRule
from .theme_rules import (
    ThemeDayMenuRule,
    ThemeSlotFilterRule,
    ThemeStarterPreferenceRule,
    ThemeFallbackPenaltyRule,
)
from .color_rules import (
    ColorPairingMenuRule,
    ColorVarietyMenuRule,
    WelcomeDrinkColorMenuRule,
)
from .cooldown_rules import (
    ItemCooldownMenuRule,
    RiceBreadGapMenuRule,
    WeekSignatureCooldownMenuRule,
)
from .nonveg_rules import (
    NonvegBiryaniWeeklyRule,
    NonvegDryPreferenceRule,
)
from .ingredient_ban_rule import IngredientBanRule
from .item_frequency_rule import ItemFrequencyRule
from .selector_frequency_rule import SelectorFrequencyRule
from .selector_history_window_rule import SelectorHistoryWindowRule
from .attribute_grouping_rule import AttributeGroupingRule
from .soft_preference_rule import SoftPreferenceRule
from .slot_composition_rule import SlotCompositionRule
from .slot_day_restriction_rule import SlotDayRestrictionRule
from .fixed_daily_item_rule import FixedDailyItemRule
from .repeatable_items_rule import RepeatableItemsRule
from .same_day_exclusion_rule import SameDayExclusionRule
from .welcome_drink_buttermilk_rule import WelcomeDrinkButtermilkRule


def _log_invalid_rule(
    rule: Optional[BaseMenuRule],
    rule_config: Dict[str, Any],
    *,
    scope: str,
) -> None:
    """Log an invalid rule with its name, type, and any reasons provided
    by the rule's ``validation_errors()`` hook. A generic "invalid" message
    stranded admins with no way to know which field was wrong.
    """
    name = rule_config.get('name') or (rule.name if rule else '<unnamed>')
    rule_type = rule_config.get('type', '?')
    errs = rule.validation_errors() if rule is not None else []
    if errs:
        logger.warning(
            "Skipping invalid %s '%s' (type=%s): %s",
            scope, name, rule_type, "; ".join(errs),
        )
    else:
        logger.warning(
            "Skipping invalid %s '%s' (type=%s): validate_config() returned False",
            scope, name, rule_type,
        )


class MenuRuleLoader:
    """Loads menu rules from JSON configuration files."""

    RULE_CLASSES = {
        'cuisine': CuisineMenuRule,
        'color_pairing': ColorPairingMenuRule,
        'color_variety': ColorVarietyMenuRule,
        'unique_items': UniqueItemsMenuRule,
        'theme_day': ThemeDayMenuRule,
        'coupling': CouplingMenuRule,
        'curd_side': CurdSideMenuRule,
        'premium': PremiumMenuRule,
        'welcome_drink_color': WelcomeDrinkColorMenuRule,
        'welcome_drink_buttermilk': WelcomeDrinkButtermilkRule,
        'week_signature_cooldown': WeekSignatureCooldownMenuRule,
        'theme_starter_preference': ThemeStarterPreferenceRule,
        'theme_fallback_penalty': ThemeFallbackPenaltyRule,
        'item_cooldown': ItemCooldownMenuRule,
        'ricebread_gap': RiceBreadGapMenuRule,
        'theme_slot_filter': ThemeSlotFilterRule,
        'nonveg_dry_preference': NonvegDryPreferenceRule,
        'nonveg_biryani_weekly': NonvegBiryaniWeeklyRule,
        'ingredient_ban': IngredientBanRule,
        'item_frequency': ItemFrequencyRule,
        'selector_frequency': SelectorFrequencyRule,
        'selector_history_window': SelectorHistoryWindowRule,
        'attribute_grouping': AttributeGroupingRule,
        'soft_preference': SoftPreferenceRule,
        'slot_composition': SlotCompositionRule,
        'slot_day_restriction': SlotDayRestrictionRule,
        'fixed_daily_item': FixedDailyItemRule,
        'repeatable_items': RepeatableItemsRule,
        'same_day_exclusion': SameDayExclusionRule,
    }

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = Path(config_path) if config_path else None
        self.rules = []

    def load_from_file(self, config_path: str = None) -> List[BaseMenuRule]:
        if config_path:
            self.config_path = Path(config_path)
        if not self.config_path or not self.config_path.exists():
            raise FileNotFoundError(f"Menu rule config file not found: {self.config_path}")
        # Resolve any ``extends`` chain into a single merged rule list, then
        # deserialize once.
        merged = self._resolve_rule_dicts(self.config_path, seen=set())
        return self.load_from_dict({'rules': merged})

    def load_for_city(self, city: Optional[str], cities_dir: str = None) -> List[BaseMenuRule]:
        """Load the ruleset for *city* from ``CITY_RULES_DIR`` (``<city>.json``),
        resolving ``extends``. Falls back to ``DEFAULT_CITY`` when the city is
        unknown/blank or has no file of its own."""
        base = Path(cities_dir or CITY_RULES_DIR)
        norm = (city or '').strip().lower()
        path = base / f"{norm}.json"
        if not norm or not path.exists():
            path = base / f"{DEFAULT_CITY}.json"
        return self.load_from_file(str(path))

    def _resolve_rule_dicts(self, path: Path, seen: set) -> List[Dict[str, Any]]:
        """Return the merged list of rule *dicts* for a city file, applying its
        ``extends`` parent first, then this file's overrides/additions."""
        path = Path(path)
        key = str(path.resolve())
        if key in seen:
            raise ValueError(f"circular 'extends' involving {path.name}")
        seen.add(key)
        with open(path, 'r') as f:
            blob = json.load(f)
        parent: List[Dict[str, Any]] = []
        ext = blob.get('extends')
        if ext:
            parent = self._resolve_rule_dicts(path.parent / f"{ext}.json", seen)
        child = list(blob.get('rules', blob.get('constraints', [])))
        return self._merge_rule_dicts(parent, child, blob.get('disable', []))

    @staticmethod
    def _merge_rule_dicts(parent, child, disable) -> List[Dict[str, Any]]:
        """Merge *child* rule dicts over *parent*: same ``name`` overrides,
        new names append (parent order preserved), names in *disable* drop.
        Nameless rules are always appended (never override).

        An override is a **per-key** merge, not a whole-dict replacement: keys
        the child omits are inherited from the parent rule of the same name.
        Whole-dict replacement silently dropped sibling keys — F5 and Cigna
        override ``nonveg_main_daily_pair`` with just ``components``, which
        deleted the city rule's ``components_by_theme`` and left their Chinese
        day with no Chinese requirement and their biryani day with no biryani.
        Inheriting the omitted keys keeps a partial override meaning "change
        this field", which is what every author of these files expects.

        To *remove* an inherited key, set it to ``null`` in the child (dropped
        below), or drop the whole rule via ``disable``.
        """
        disable = set(disable or [])
        by_name: Dict[str, Any] = {}
        order: List[str] = []
        anon: List[Dict[str, Any]] = []
        for r in list(parent) + list(child):
            n = r.get('name')
            if not n:
                anon.append(r)
                continue
            if n not in by_name:
                order.append(n)
                by_name[n] = dict(r)
                continue
            merged = {**by_name[n], **r}
            inherited = sorted(set(by_name[n]) - set(r))
            if inherited:
                logger.info(
                    "Rule %r overridden; inheriting unspecified key(s) from the "
                    "base rule: %s", n, ", ".join(inherited),
                )
            by_name[n] = {k: v for k, v in merged.items() if v is not None}
        return [by_name[n] for n in order if n not in disable] + anon

    def load_from_dict(self, config_data: Dict[str, Any]) -> List[BaseMenuRule]:
        self.rules = []
        rules_list = config_data.get('rules', config_data.get('constraints', []))
        for rule_config in rules_list:
            try:
                rule = self._create_rule(rule_config)
                if rule and rule.validate_config():
                    self.rules.append(rule)
                else:
                    _log_invalid_rule(rule, rule_config, scope="rule")
            except (ValueError, KeyError, TypeError) as e:
                logger.warning("Error creating rule: %s", e)
        logger.info("Loaded %d menu rule(s)", len(self.rules))
        return self.rules

    def _create_rule(self, rule_config: Dict[str, Any]) -> Optional[BaseMenuRule]:
        rule_type = rule_config.get('type', '').lower()
        if rule_type not in self.RULE_CLASSES:
            raise ValueError(f"Unknown rule type: {rule_type}")
        return self.RULE_CLASSES[rule_type](rule_config)

    @staticmethod
    def _parse_client_block(
        client_block: Any, counter_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Normalise a per-client ``client_rules.json`` value.

        Accepts the legacy list form ``[rule, …]`` or the object form::

            {"disable": [...], "rules": [...], "constant_items": {...},
             "counters": {"<counter name>": {"disable": [...], "rules": [...],
                                             "constant_items": {...}}}}

        ``counters`` scopes an override to one counter of a multi-counter client.
        A client-level entry applies to every counter, which is wrong for rules
        that only make sense for one station: L&T's "Non Veg Lunch" counter is
        themed biryani every day, so the weekly nonveg-biryani cap has to come
        off *there* — but leaving it off client-wide would silently disable it if
        another L&T counter ever gains a nonveg_main slot.

        Counter entries are layered over the client-level ones, so shared
        overrides stay declared once.
        """
        empty = {'disable': [], 'rules': [], 'constant_items': {}}
        if isinstance(client_block, list):
            return {**empty, 'rules': list(client_block)}
        if not isinstance(client_block, dict):
            return dict(empty)

        def _layer(block: Dict[str, Any]) -> Dict[str, Any]:
            rules = block.get('rules', block.get('constraints', []))
            return {
                'disable': list(block.get('disable') or []),
                'rules': list(rules or []),
                'constant_items': dict(block.get('constant_items') or {}),
            }

        merged = _layer(client_block)
        counters = client_block.get('counters')
        if counter_name and isinstance(counters, dict):
            scoped = counters.get(counter_name)
            if isinstance(scoped, dict):
                layer = _layer(scoped)
                merged['disable'] = merged['disable'] + layer['disable']
                merged['rules'] = merged['rules'] + layer['rules']
                merged['constant_items'] = {
                    **merged['constant_items'], **layer['constant_items'],
                }
        return merged

    @classmethod
    def _read_client_blob(cls) -> Dict[str, Any]:
        path = Path(CLIENT_RULES_CONFIG_PATH)
        if not path.exists():
            return {}
        try:
            with open(path, 'r') as f:
                blob = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read client_rules.json: %s", exc)
            return {}
        return blob if isinstance(blob, dict) else {}

    def get_shared_categories(self, client_name: str) -> List[str]:
        """Base slots this client serves identically across all its counters.

        Read from the client's top-level ``shared_categories`` list in
        ``client_rules.json`` (empty when unset or the entry is the legacy bare
        rule list). The planner uses it to pin the primary counter's choice for
        each of these slots into the other counters on the matching day — the
        "common categories are the same across counters" requirement. Cross-
        counter coordination is client-orchestrated, so this is a hint the
        planner reads, not a solver rule.
        """
        block = self._read_client_blob().get(client_name)
        if not isinstance(block, dict):
            return []
        raw = block.get('shared_categories') or []
        if not isinstance(raw, list):
            return []
        # De-dupe, drop blanks, preserve order.
        seen: set = set()
        out: List[str] = []
        for c in raw:
            s = str(c).strip()
            if s and s not in seen:
                seen.add(s)
                out.append(s)
        return out

    def get_client_constant_items(
        self, client_name: str, counter_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return ``constant_items`` for *client_name* (empty dict if unset).

        *counter_name* layers that counter's ``counters`` entry over the
        client-level one.
        """
        block = self._read_client_blob().get(client_name)
        if not block:
            return {}
        return self._parse_client_block(block, counter_name)['constant_items']

    def load_for_client(
        self, client_name: str, generic_rules: List[BaseMenuRule],
        counter_name: Optional[str] = None,
    ) -> List[BaseMenuRule]:
        """Merge city/generic rules with per-client overrides for *client_name*.

        Reads ``CLIENT_RULES_CONFIG_PATH`` fresh every call. Client entries may
        be a legacy rule list or ``{disable, rules, constant_items}``. Merge
        semantics match city ``extends``: same ``name`` overrides, ``disable``
        drops by name. Missing file / unknown client → *generic_rules* unchanged.

        *counter_name* additionally applies that counter's ``counters`` entry, so
        an override can be scoped to one station of a multi-counter client.
        """
        client_block = self._read_client_blob().get(client_name)
        if not client_block:
            return list(generic_rules)

        parsed = self._parse_client_block(client_block, counter_name)
        parent_dicts = [
            dict(getattr(r, 'config', {}) or {})
            for r in generic_rules
            if getattr(r, 'config', None) is not None
        ]
        # Preserve rules that somehow lack a config dict (tests may pass stubs).
        stubs = [r for r in generic_rules if getattr(r, 'config', None) is None]
        merged_dicts = self._merge_rule_dicts(
            parent_dicts, parsed['rules'], parsed['disable'],
        )
        merged: List[BaseMenuRule] = list(stubs)
        for rule_cfg in merged_dicts:
            try:
                rule = self._create_rule(rule_cfg)
                if rule and rule.validate_config():
                    merged.append(rule)
                else:
                    _log_invalid_rule(
                        rule, rule_cfg,
                        scope=f"per-client rule for {client_name}",
                    )
            except (ValueError, KeyError, TypeError) as exc:
                logger.warning(
                    "Error creating per-client rule for %s: %s",
                    client_name, exc)
        n_extra = len(parsed['rules'])
        n_disabled = len(parsed['disable'])
        logger.info(
            "Merged client '%s'%s: %d override/add rule(s), %d disabled → %d total",
            client_name, f" counter '{counter_name}'" if counter_name else "",
            n_extra, n_disabled, len(merged),
        )
        return merged

    def get_rules_by_type(self, rule_type: str) -> List[BaseMenuRule]:
        return [r for r in self.rules if r.rule_type.value == rule_type]

    def get_enabled_rules(self) -> List[BaseMenuRule]:
        return list(self.rules)
