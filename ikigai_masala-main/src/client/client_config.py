"""
Client configuration loader.

Reads clients.json and provides per-client slot lists, slot counts,
and menu category information.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

from src.constants import (
    BASE_SLOT_NAMES as BASE_SLOTS,
    CONST_SLOTS,
    SLOT_SUFFIX_SEP,
)

ALL_SLOTS: List[str] = list(BASE_SLOTS) + list(CONST_SLOTS)

DEFAULT_THEME_MAP: Dict[str, str] = {
    'monday': 'mix',
    'tuesday': 'chinese',
    'wednesday': 'biryani',
    'thursday': 'south',
    'friday': 'north',
}

AVAILABLE_THEMES: List[str] = ['mix', 'chinese', 'biryani', 'south', 'north']


@dataclass
class ClientConfig:
    name: str
    menu_category: str
    active_slots: List[str] = field(default_factory=list)
    slot_counts: Dict[str, int] = field(default_factory=dict)
    theme_map: Dict[str, str] = field(default_factory=dict)


def _dedupe_preserve_order(values: List[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for v in values:
        if v not in seen:
            out.append(v)
            seen.add(v)
    return out


def _expand_slot_ids(base_slot: str, count: int) -> List[str]:
    n = int(count)
    if n <= 0:
        return []
    if n == 1:
        return [base_slot]
    return [f'{base_slot}{SLOT_SUFFIX_SEP}{i}' for i in range(1, n + 1)]


class ClientConfigLoader:
    """Loads and provides access to client configuration from a JSON file."""

    _write_lock = threading.Lock()

    def __init__(self, config_path: str):
        self._path = Path(config_path)
        self._data: Dict = {}
        self._clients: Dict[str, Dict] = {}
        self._load()

    def _load(self):
        with open(self._path) as f:
            self._data = json.load(f)
        self._clients = {c['name']: c for c in self._data['clients']}

    def _save(self):
        """Write current data back to disk."""
        with open(self._path, 'w') as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)
            f.write('\n')

    @property
    def client_names(self) -> List[str]:
        return [c['name'] for c in self._data['clients']]

    @property
    def menu_categories(self) -> Dict[str, List[str]]:
        return self._data['menu_categories']

    @property
    def fallback_menu_category(self) -> str:
        return self._data.get('fallback_menu_category', 'menu_cat_3')

    @property
    def core_min_one_slots(self) -> List[str]:
        return self._data.get('core_min_one_slots', [])

    @property
    def constant_slots(self) -> List[str]:
        return self._data.get('constant_slots', CONST_SLOTS)

    def get_client(self, name: str) -> ClientConfig:
        """Return a fully-populated ClientConfig for the given client."""
        if name not in self._clients:
            raise ValueError(f"Unknown client: {name}")
        entry = self._clients[name]
        cat = entry['menu_category']
        slot_counts = self.get_slot_counts_for_client(name)

        base_to_show = self.get_slots_for_menu_category(cat)
        active: List[str] = []
        for slot in base_to_show:
            if slot in CONST_SLOTS:
                active.append(slot)
            else:
                active.extend(_expand_slot_ids(slot, slot_counts.get(slot, 1)))
        active = _dedupe_preserve_order(active)

        theme_map = self.get_theme_map_for_client(name)

        return ClientConfig(
            name=name,
            menu_category=cat,
            active_slots=active,
            slot_counts=slot_counts,
            theme_map=theme_map,
        )

    def get_client_menu_category(self, name: str) -> str:
        if name not in self._clients:
            return self.fallback_menu_category
        return self._clients[name]['menu_category']

    def get_slots_for_menu_category(self, category: str) -> List[str]:
        cats = self._data['menu_categories']
        slots = cats.get(category, cats.get(self.fallback_menu_category, []))
        return _dedupe_preserve_order(list(slots))

    def get_slot_counts_for_client(self, name: str) -> Dict[str, int]:
        counts = {s: 1 for s in BASE_SLOTS}
        overrides = self._data.get('slot_count_overrides', {}).get(name, {})
        for k, v in overrides.items():
            if k in counts:
                counts[k] = max(0, int(v))
        for must in self.core_min_one_slots:
            counts[must] = max(1, int(counts.get(must, 1)))
        return counts

    def get_slots_for_client(self, name: str) -> List[str]:
        return self.get_client(name).active_slots

    def get_theme_map_for_client(self, name: str) -> Dict[str, str]:
        """Return the merged theme map for a client (global defaults + overrides)."""
        merged = dict(DEFAULT_THEME_MAP)
        overrides = self._data.get('theme_overrides', {}).get(name, {})
        for day, theme in overrides.items():
            day_lower = day.lower()
            if day_lower in merged and theme in AVAILABLE_THEMES:
                merged[day_lower] = theme
        return merged

    # ----- Mutation methods -----

    def create_client(self, name: str, menu_category: str) -> None:
        """Add a new client to the config."""
        with self._write_lock:
            if name in self._clients:
                raise ValueError(f"Client '{name}' already exists")
            cats = self._data['menu_categories']
            if menu_category not in cats:
                raise ValueError(f"Unknown menu category: {menu_category}")
            entry = {'name': name, 'menu_category': menu_category}
            self._data['clients'].append(entry)
            self._clients[name] = entry
            self._save()

    def delete_client(self, name: str) -> None:
        """Remove a client and its associated overrides."""
        with self._write_lock:
            if name not in self._clients:
                raise ValueError(f"Unknown client: {name}")
            self._data['clients'] = [
                c for c in self._data['clients'] if c['name'] != name
            ]
            self._clients.pop(name, None)
            self._data.get('slot_count_overrides', {}).pop(name, None)
            self._data.get('theme_overrides', {}).pop(name, None)
            self._save()

    def update_client_menu_category(self, name: str, menu_category: str) -> None:
        """Change a client's menu category."""
        with self._write_lock:
            if name not in self._clients:
                raise ValueError(f"Unknown client: {name}")
            cats = self._data['menu_categories']
            if menu_category not in cats:
                raise ValueError(f"Unknown menu category: {menu_category}")
            self._clients[name]['menu_category'] = menu_category
            self._save()

    def update_client_slot_counts(self, name: str, overrides: Dict[str, int]) -> None:
        """Update slot count overrides for a client."""
        with self._write_lock:
            if name not in self._clients:
                raise ValueError(f"Unknown client: {name}")
            sco = self._data.setdefault('slot_count_overrides', {})
            # Only store overrides where count != 1
            filtered = {k: v for k, v in overrides.items()
                        if k in BASE_SLOTS and int(v) != 1}
            if filtered:
                sco[name] = {k: int(v) for k, v in filtered.items()}
            else:
                sco.pop(name, None)
            self._save()

    def update_client_theme_overrides(self, name: str, theme_map: Dict[str, str]) -> None:
        """Update per-client theme day overrides."""
        with self._write_lock:
            if name not in self._clients:
                raise ValueError(f"Unknown client: {name}")
            to = self._data.setdefault('theme_overrides', {})
            # Only store overrides that differ from global defaults
            diff = {day: theme for day, theme in theme_map.items()
                    if day in DEFAULT_THEME_MAP
                    and theme in AVAILABLE_THEMES
                    and theme != DEFAULT_THEME_MAP.get(day)}
            if diff:
                to[name] = diff
            else:
                to.pop(name, None)
            self._save()

    def update_client_slots(self, name: str, active_base_slots: List[str]) -> None:
        """Update a client's active slots by creating/assigning a matching menu category."""
        with self._write_lock:
            if name not in self._clients:
                raise ValueError(f"Unknown client: {name}")
            # Check if any existing category matches exactly
            cats = self._data['menu_categories']
            target_set = set(active_base_slots)
            for cat_name, cat_slots in cats.items():
                if set(cat_slots) == target_set:
                    self._clients[name]['menu_category'] = cat_name
                    self._save()
                    return
            # Create a new custom category
            existing_nums = []
            for k in cats:
                if k.startswith('menu_cat_'):
                    try:
                        existing_nums.append(int(k.split('_')[-1]))
                    except ValueError:
                        pass
            new_num = max(existing_nums, default=0) + 1
            new_cat = f'menu_cat_{new_num}'
            cats[new_cat] = list(active_base_slots)
            self._clients[name]['menu_category'] = new_cat
            self._save()

    def validate(self):
        """Validate configuration consistency. Raises ValueError on problems."""
        names = self.client_names
        if len(set(names)) != len(names):
            dupes = [n for n in names if names.count(n) > 1]
            raise ValueError(f"Duplicate client names: {set(dupes)}")

        cats = self._data['menu_categories']
        for entry in self._data['clients']:
            cat = entry['menu_category']
            if cat not in cats:
                raise ValueError(f"Client '{entry['name']}' references unknown category: {cat}")

        all_slots_set = set(ALL_SLOTS)
        for cat_name, slots in cats.items():
            bad = [s for s in slots if s not in all_slots_set]
            if bad:
                raise ValueError(f"Category '{cat_name}' has unknown slot(s): {bad}")

        overrides = self._data.get('slot_count_overrides', {})
        for client, ovr in overrides.items():
            if client not in self._clients:
                raise ValueError(f"slot_count_overrides has unknown client: {client}")
            bad_keys = [k for k in ovr if k not in BASE_SLOTS]
            if bad_keys:
                raise ValueError(f"slot_count_overrides[{client}] has unknown slot(s): {bad_keys}")

        theme_ovr = self._data.get('theme_overrides', {})
        for client, themes in theme_ovr.items():
            if client not in self._clients:
                raise ValueError(f"theme_overrides has unknown client: {client}")
            for day, theme in themes.items():
                if day.lower() not in DEFAULT_THEME_MAP:
                    raise ValueError(f"theme_overrides[{client}] has invalid day: {day}")
                if theme not in AVAILABLE_THEMES:
                    raise ValueError(f"theme_overrides[{client}] has invalid theme: {theme}")
