"""
Client configuration loader — Supabase backend.

Every read queries Supabase directly so any change made via the UI,
API, or dashboard is immediately reflected on the next call.
"""

from __future__ import annotations

import json
import os
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
                # Try Streamlit secrets first, then fall back to env vars
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
        """
        Parameters
        ----------
        config_path : str
            Kept for backward-compatibility with call sites that pass the old
            JSON path.  The value is ignored; all data comes from Supabase.
        """
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
        # value is stored as JSONB — supabase-py normally returns it already
        # parsed.  If it arrives as a raw JSON string (e.g. '["a","b"]'),
        # try to parse it; plain strings like 'menu_cat_3' are returned as-is.
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
        rows = (
            self._sb.table('menu_categories')
            .select('name, slots')
            .execute()
        )
        return {r['name']: r['slots'] for r in rows.data}

    @property
    def fallback_menu_category(self) -> str:
        val = self._setting('fallback_menu_category')
        return val if val else 'menu_cat_3'

    @property
    def core_min_one_slots(self) -> List[str]:
        val = self._setting('core_min_one_slots')
        return val if val else []

    @property
    def constant_slots(self) -> List[str]:
        val = self._setting('constant_slots')
        return val if val else list(CONST_SLOTS)

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
        row = (
            self._sb.table('clients')
            .select('menu_category')
            .eq('name', name)
            .maybe_single()
            .execute()
        )
        if not row.data:
            return self.fallback_menu_category
        return row.data['menu_category']

    def get_slots_for_menu_category(self, category: str) -> List[str]:
        row = (
            self._sb.table('menu_categories')
            .select('slots')
            .eq('name', category)
            .maybe_single()
            .execute()
        )
        if row.data:
            return _dedupe_preserve_order(row.data['slots'])
        # Fallback category
        fb = (
            self._sb.table('menu_categories')
            .select('slots')
            .eq('name', self.fallback_menu_category)
            .maybe_single()
            .execute()
        )
        return _dedupe_preserve_order(fb.data['slots']) if fb.data else []

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

    def get_slots_for_client(self, name: str) -> List[str]:
        return self.get_client(name).active_slots

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
    # These write directly to Supabase.  The next read from *any* process
    # (this one, another API replica, or even the Supabase dashboard) will
    # see the updated data immediately.

    def create_client(self, name: str, menu_category: str) -> None:
        cats = self.menu_categories
        if menu_category not in cats:
            raise ValueError(f"Unknown menu category: {menu_category}")
        # Supabase PK constraint will reject duplicates
        self._sb.table('clients').insert({
            'name': name,
            'menu_category': menu_category,
        }).execute()

    def delete_client(self, name: str) -> None:
        # Verify client exists first
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

    def update_client_menu_category(self, name: str, menu_category: str) -> None:
        cats = self.menu_categories
        if menu_category not in cats:
            raise ValueError(f"Unknown menu category: {menu_category}")
        self._sb.table('clients').update({
            'menu_category': menu_category,
        }).eq('name', name).execute()

    def update_client_slot_counts(self, name: str, overrides: Dict[str, int]) -> None:
        # Clear existing overrides for this client
        self._sb.table('slot_count_overrides').delete().eq('client_name', name).execute()
        # Insert only non-default (count != 1) overrides
        rows = [
            {'client_name': name, 'slot': k, 'count': int(v)}
            for k, v in overrides.items()
            if k in BASE_SLOTS and int(v) != 1
        ]
        if rows:
            self._sb.table('slot_count_overrides').insert(rows).execute()

    def update_client_theme_overrides(self, name: str, theme_map: Dict[str, str]) -> None:
        # Clear existing overrides for this client
        self._sb.table('theme_overrides').delete().eq('client_name', name).execute()
        # Insert only values that differ from global defaults
        rows = [
            {'client_name': name, 'day': day, 'theme': theme}
            for day, theme in theme_map.items()
            if day in DEFAULT_THEME_MAP
            and theme in AVAILABLE_THEMES
            and theme != DEFAULT_THEME_MAP.get(day)
        ]
        if rows:
            self._sb.table('theme_overrides').insert(rows).execute()

    def update_client_slots(self, name: str, active_base_slots: List[str]) -> None:
        """Update a client's active slots.

        If an existing menu category matches the slot set, re-use it.
        Otherwise create a new category.
        """
        cats = self.menu_categories
        target_set = set(active_base_slots)

        # Check for an existing match
        for cat_name, cat_slots in cats.items():
            if set(cat_slots) == target_set:
                self._sb.table('clients').update({
                    'menu_category': cat_name,
                }).eq('name', name).execute()
                return

        # Create a new custom category
        existing_nums = []
        for k in cats:
            if k.startswith('menu_cat_'):
                try:
                    existing_nums.append(int(k.split('_')[-1]))
                except ValueError:
                    pass
        new_cat = f'menu_cat_{max(existing_nums, default=0) + 1}'

        self._sb.table('menu_categories').insert({
            'name': new_cat,
            'slots': list(active_base_slots),
        }).execute()

        self._sb.table('clients').update({
            'menu_category': new_cat,
        }).eq('name', name).execute()

    # ---- validation --------------------------------------------------------

    def validate(self):
        """Validate configuration consistency.  Raises ValueError on problems."""
        # DB primary keys enforce unique client names, so just check referential
        # integrity and slot validity.

        cats = self.menu_categories
        rows = self._sb.table('clients').select('name, menu_category').execute()
        for r in rows.data:
            if r['menu_category'] not in cats:
                raise ValueError(
                    f"Client '{r['name']}' references unknown category: {r['menu_category']}"
                )

        all_slots_set = set(ALL_SLOTS)
        for cat_name, slots in cats.items():
            bad = [s for s in slots if s not in all_slots_set]
            if bad:
                raise ValueError(f"Category '{cat_name}' has unknown slot(s): {bad}")

        # Validate slot_count_overrides reference valid clients and slots
        sco_rows = self._sb.table('slot_count_overrides').select('client_name, slot').execute()
        client_set = {r['name'] for r in rows.data}
        base_set = set(BASE_SLOTS)
        for r in sco_rows.data:
            if r['client_name'] not in client_set:
                raise ValueError(
                    f"slot_count_overrides has unknown client: {r['client_name']}"
                )
            if r['slot'] not in base_set:
                raise ValueError(
                    f"slot_count_overrides[{r['client_name']}] has unknown slot: {r['slot']}"
                )

        # Validate theme_overrides
        to_rows = self._sb.table('theme_overrides').select('client_name, day, theme').execute()
        for r in to_rows.data:
            if r['client_name'] not in client_set:
                raise ValueError(
                    f"theme_overrides has unknown client: {r['client_name']}"
                )
            if r['day'].lower() not in DEFAULT_THEME_MAP:
                raise ValueError(
                    f"theme_overrides[{r['client_name']}] has invalid day: {r['day']}"
                )
            if r['theme'] not in AVAILABLE_THEMES:
                raise ValueError(
                    f"theme_overrides[{r['client_name']}] has invalid theme: {r['theme']}"
                )
