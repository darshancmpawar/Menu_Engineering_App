"""
Client configuration loader — Supabase backend.

Every read queries Supabase directly so any change made via the UI,
API, or dashboard is immediately reflected on the next call.

Schema:
    menu_categories (name TEXT PK, slots TEXT[])
    clients         (name TEXT PK, menu_category TEXT FK → menu_categories.name)
    slot_count_overrides (client_name, slot, count)
    theme_overrides      (client_name, day, theme)
    app_settings         (key, value)
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from src.constants import (
    BASE_SLOT_NAMES as BASE_SLOTS,
    CONST_SLOTS,
    SLOT_SUFFIX_SEP,
)

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


# ---------------------------------------------------------------------------
# Supabase client — shared across all loader instances
# ---------------------------------------------------------------------------
_sb_client = None
_sb_lock = threading.Lock()


def _get_supabase():
    """Return a module-level Supabase client (created once, reused)."""
    global _sb_client
    if _sb_client is None:
        with _sb_lock:
            if _sb_client is None:
                from supabase import create_client
                try:
                    import streamlit as st
                    url = st.secrets['SUPABASE_URL']
                    key = st.secrets['SUPABASE_KEY']
                except Exception:
                    url = os.environ['SUPABASE_URL']
                    key = os.environ['SUPABASE_KEY']
                _sb_client = create_client(url, key)
    return _sb_client


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

class ClientConfigLoader:
    """
    Loads client configuration from Supabase.

    Every property and method issues a live query — there is no in-memory
    cache, so data is always consistent with the database.
    """

    def __init__(self, config_path: str = ''):
        self._sb = _get_supabase()

    # ---- internal helpers --------------------------------------------------

    def _setting(self, key: str):
        """Read a single value from the app_settings table."""
        row = (
            self._sb.table('app_settings')
            .select('value')
            .eq('key', key)
            .maybe_single()
            .execute()
        )
        if row.data is None:
            return None
        val = row.data['value']
        if isinstance(val, str):
            try:
                return json.loads(val)
            except (json.JSONDecodeError, ValueError):
                return val
        return val

    # ---- read properties ---------------------------------------------------

    @property
    def client_names(self) -> List[str]:
        rows = (
            self._sb.table('clients')
            .select('name')
            .order('name')
            .execute()
        )
        return [r['name'] for r in rows.data]

    @property
    def menu_categories(self) -> Dict[str, List[str]]:
        """Return {category_name: [slot, ...]} from menu_categories table."""
        rows = (
            self._sb.table('menu_categories')
            .select('name, slots')
            .execute()
        )
        return {r['name']: r['slots'] for r in rows.data}

    @property
    def core_min_one_slots(self) -> List[str]:
        val = self._setting('core_min_one_slots')
        return val if val else []

    @property
    def constant_slots(self) -> List[str]:
        val = self._setting('constant_slots')
        return val if val else list(CONST_SLOTS)

    @property
    def fallback_menu_category(self) -> Optional[str]:
        val = self._setting('fallback_menu_category')
        return val if isinstance(val, str) else None

    # ---- client read methods -----------------------------------------------

    def get_client(self, name: str) -> ClientConfig:
        """Return a fully-populated ClientConfig for the given client."""
        row = (
            self._sb.table('clients')
            .select('name, menu_category')
            .eq('name', name)
            .maybe_single()
            .execute()
        )
        if not row.data:
            raise ValueError(f"Unknown client: {name}")

        entry = row.data
        base_slots = self.get_slots_for_menu_category(entry.get('menu_category', ''))
        slot_counts = self.get_slot_counts_for_client(name)

        # Expand base slots using slot counts (e.g. veg_dry x2 → veg_dry__1, veg_dry__2)
        expanded: List[str] = []
        for slot in base_slots:
            if slot in CONST_SLOTS:
                expanded.append(slot)
            else:
                expanded.extend(_expand_slot_ids(slot, slot_counts.get(slot, 1)))
        expanded = _dedupe_preserve_order(expanded)

        theme_map = self.get_theme_map_for_client(name)

        return ClientConfig(
            name=name,
            active_slots=expanded,
            slot_counts=slot_counts,
            theme_map=theme_map,
        )

    def get_client_menu_category(self, name: str) -> str:
        """Return the menu_category name for a client."""
        row = (
            self._sb.table('clients')
            .select('menu_category')
            .eq('name', name)
            .maybe_single()
            .execute()
        )
        if not row.data:
            raise ValueError(f"Unknown client: {name}")
        return row.data.get('menu_category', '')

    def get_active_slots_for_client(self, name: str) -> List[str]:
        """Return the base active slots for a client (via its menu_category)."""
        cat_name = self.get_client_menu_category(name)
        return self.get_slots_for_menu_category(cat_name)

    def get_slots_for_menu_category(self, cat_name: str) -> List[str]:
        """Return slots for a menu_category; falls back to defaults."""
        if not cat_name:
            return list(BASE_SLOTS)
        row = (
            self._sb.table('menu_categories')
            .select('slots')
            .eq('name', cat_name)
            .maybe_single()
            .execute()
        )
        if row.data and row.data.get('slots'):
            return row.data['slots']
        # Fallback: try the fallback category
        fb = self.fallback_menu_category
        if fb and fb != cat_name:
            return self.get_slots_for_menu_category(fb)
        return list(BASE_SLOTS)

    def get_slot_counts_for_client(self, name: str) -> Dict[str, int]:
        counts = {s: 1 for s in BASE_SLOTS}
        rows = (
            self._sb.table('slot_count_overrides')
            .select('slot, count')
            .eq('client_name', name)
            .execute()
        )
        for r in rows.data:
            if r['slot'] in counts:
                counts[r['slot']] = max(0, int(r['count']))
        for must in self.core_min_one_slots:
            counts[must] = max(1, int(counts.get(must, 1)))
        return counts

    def get_theme_map_for_client(self, name: str) -> Dict[str, str]:
        """Return merged theme map (global defaults + per-client overrides)."""
        merged = dict(DEFAULT_THEME_MAP)
        rows = (
            self._sb.table('theme_overrides')
            .select('day, theme')
            .eq('client_name', name)
            .execute()
        )
        for r in rows.data:
            day_lower = r['day'].lower()
            if day_lower in merged and r['theme'] in AVAILABLE_THEMES:
                merged[day_lower] = r['theme']
        return merged

    # ---- mutation methods --------------------------------------------------

    def find_or_create_menu_category(self, slots: List[str]) -> str:
        """Find an existing menu_category whose slots match exactly, or create a new one.

        Returns the category name.
        """
        sorted_slots = sorted(slots)
        categories = self.menu_categories
        for cat_name, cat_slots in categories.items():
            if sorted(cat_slots) == sorted_slots:
                return cat_name

        # No match — create a new category
        # Name: menu_cat_N where N is next available number
        existing_nums = []
        for cat_name in categories:
            if cat_name.startswith('menu_cat_'):
                try:
                    existing_nums.append(int(cat_name.split('_')[-1]))
                except ValueError:
                    pass
        next_num = max(existing_nums, default=0) + 1
        new_name = f'menu_cat_{next_num}'

        self._sb.table('menu_categories').insert({
            'name': new_name,
            'slots': list(slots),
        }).execute()
        return new_name

    def create_client(self, name: str, active_slots: List[str]) -> None:
        """Create a new client. Auto-assigns or creates a menu_category."""
        cat_name = self.find_or_create_menu_category(active_slots)
        self._sb.table('clients').insert({
            'name': name,
            'menu_category': cat_name,
        }).execute()

    def delete_client(self, name: str) -> None:
        row = (
            self._sb.table('clients')
            .select('name')
            .eq('name', name)
            .maybe_single()
            .execute()
        )
        if not row.data:
            raise ValueError(f"Unknown client: {name}")
        # CASCADE on FK deletes slot_count_overrides & theme_overrides
        self._sb.table('clients').delete().eq('name', name).execute()

    def update_client_slots(self, name: str, active_slots: List[str]) -> None:
        """Update a client's active slots by finding/creating a matching menu_category."""
        cat_name = self.find_or_create_menu_category(active_slots)
        self._sb.table('clients').update({
            'menu_category': cat_name,
        }).eq('name', name).execute()

    def update_client_slot_counts(self, name: str, overrides: Dict[str, int]) -> None:
        self._sb.table('slot_count_overrides').delete().eq('client_name', name).execute()
        rows = [
            {'client_name': name, 'slot': k, 'count': int(v)}
            for k, v in overrides.items()
            if k in BASE_SLOTS and int(v) != 1
        ]
        if rows:
            self._sb.table('slot_count_overrides').insert(rows).execute()

    def update_client_theme_overrides(self, name: str, theme_map: Dict[str, str]) -> None:
        self._sb.table('theme_overrides').delete().eq('client_name', name).execute()
        rows = [
            {'client_name': name, 'day': day, 'theme': theme}
            for day, theme in theme_map.items()
            if day in DEFAULT_THEME_MAP
            and theme in AVAILABLE_THEMES
            and theme != DEFAULT_THEME_MAP.get(day)
        ]
        if rows:
            self._sb.table('theme_overrides').insert(rows).execute()

    # ---- validation --------------------------------------------------------

    def validate(self):
        """Validate configuration consistency. Raises ValueError on problems."""
        all_slots_set = set(BASE_SLOTS) | set(CONST_SLOTS)

        # Validate menu_categories
        cats = self.menu_categories
        for cat_name, cat_slots in cats.items():
            bad = [s for s in cat_slots if s not in all_slots_set]
            if bad:
                raise ValueError(f"Category '{cat_name}' has unknown slot(s): {bad}")

        # Validate clients
        rows = self._sb.table('clients').select('name, menu_category').execute()
        client_set = set()
        for r in rows.data:
            client_set.add(r['name'])
            cat = r.get('menu_category', '')
            if cat and cat not in cats:
                raise ValueError(f"Client '{r['name']}' references unknown category: {cat}")

        base_set = set(BASE_SLOTS)
        sco_rows = self._sb.table('slot_count_overrides').select('client_name, slot').execute()
        for r in sco_rows.data:
            if r['client_name'] not in client_set:
                raise ValueError(f"slot_count_overrides has unknown client: {r['client_name']}")
            if r['slot'] not in base_set:
                raise ValueError(f"slot_count_overrides[{r['client_name']}] has unknown slot: {r['slot']}")

        to_rows = self._sb.table('theme_overrides').select('client_name, day, theme').execute()
        for r in to_rows.data:
            if r['client_name'] not in client_set:
                raise ValueError(f"theme_overrides has unknown client: {r['client_name']}")
            if r['day'].lower() not in DEFAULT_THEME_MAP:
                raise ValueError(f"theme_overrides[{r['client_name']}] has invalid day: {r['day']}")
            if r['theme'] not in AVAILABLE_THEMES:
                raise ValueError(f"theme_overrides[{r['client_name']}] has invalid theme: {r['theme']}")
