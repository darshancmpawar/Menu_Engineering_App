"""
History manager for menu planning.

Loads history from Supabase dataframes, filters by client, computes bans
and signatures, and persists completed weeks back to Supabase.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Dict, List, Optional, Set

import pandas as pd

from ..preprocessor.column_mapper import _norm_str


class HistoryManager:
    """Encapsulates menu history for cooldown and signature operations."""

    def __init__(self):
        self._long: Optional[pd.DataFrame] = None
        self._weeks: Optional[pd.DataFrame] = None

    # ----- Loading -----

    def load_from_dataframes(
        self,
        long_df: Optional[pd.DataFrame] = None,
        weeks_df: Optional[pd.DataFrame] = None,
    ) -> 'HistoryManager':
        """Load history from existing DataFrames. Returns self for chaining."""
        self._long = self._ensure_long(long_df)
        self._weeks = self._ensure_weeks(weeks_df)
        return self

    # ----- Schema validation -----

    @staticmethod
    def _ensure_long(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
        if df is None or len(df) == 0:
            return None
        h = df.copy()
        if 'service_date' not in h.columns or 'item_base' not in h.columns:
            return None
        h['service_date'] = pd.to_datetime(h['service_date'], errors='coerce').dt.date
        h['item_base'] = h['item_base'].map(_norm_str)
        if 'slot' in h.columns:
            h['slot'] = h['slot'].map(_norm_str)
        if 'client_name' in h.columns:
            h['client_name'] = h['client_name'].map(_norm_str)
        h = h[h['service_date'].notna() & (h['item_base'] != '')]
        return h

    @staticmethod
    def _ensure_weeks(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
        if df is None or len(df) == 0:
            return None
        h = df.copy()
        if 'week_start' not in h.columns or 'week_signature' not in h.columns:
            return None
        h['week_start'] = pd.to_datetime(h['week_start'], errors='coerce').dt.date
        h['week_signature'] = h['week_signature'].astype(str)
        if 'client_name' in h.columns:
            h['client_name'] = h['client_name'].map(_norm_str)
        h = h[h['week_start'].notna()]
        return h

    # ----- Filtering -----

    def filter_by_client(self, client_name: str) -> 'HistoryManager':
        """Return a new HistoryManager filtered to a single client."""
        c = _norm_str(client_name) if client_name else ''
        hm = HistoryManager()
        hm._long = self._long
        hm._weeks = self._weeks
        if not c:
            return hm
        if hm._long is not None and 'client_name' in hm._long.columns:
            hm._long = hm._long[hm._long['client_name'] == c]
        if hm._weeks is not None and 'client_name' in hm._weeks.columns:
            hm._weeks = hm._weeks[hm._weeks['client_name'] == c]
        return hm

    # ----- Ban computation -----

    def banned_items_by_date(
        self,
        dates: List[dt.date],
        cooldown_days: int = 20,
        const_slots: List[str] = (),
        repeatable_items: Set[str] = frozenset(),
    ) -> Dict[dt.date, Set[str]]:
        """Return banned items per date based on recent usage."""
        h = self._long
        if h is None:
            return {d: set() for d in dates}
        const_set = set(const_slots)
        out: Dict[dt.date, Set[str]] = {}
        for d in dates:
            start = d - dt.timedelta(days=cooldown_days)
            m = (h['service_date'] >= start) & (h['service_date'] < d)
            if 'slot' in h.columns:
                m &= ~h['slot'].isin(const_set)
            banned = set(h.loc[m, 'item_base'].tolist()) - set(repeatable_items)
            out[d] = banned
        return out

    def selector_banned_by_date(
        self,
        dates: List[dt.date],
        matching_items: Set[str],
        window_days: int,
    ) -> Dict[dt.date, Set[str]]:
        """Ban a whole selector on dates within ``window_days`` of its last use.

        *matching_items* are the (lower-cased) item names that satisfy the
        selector. For each planned date, if ANY of them was served in history
        inside ``[date - window_days, date)``, every one of them is banned on
        that date — the selector-level analogue of ``banned_items_by_date``.
        Cross-week cadences ("fish once per 15 days") are enforced this way.
        """
        h = self._long
        if h is None or not matching_items or not window_days:
            return {d: set() for d in dates}
        matching = {str(m).strip().lower() for m in matching_items}
        # item_base is already _norm_str'd (lower-cased) in _ensure_long.
        served = h[h['item_base'].isin(matching)]
        out: Dict[dt.date, Set[str]] = {}
        for d in dates:
            start = d - dt.timedelta(days=window_days)
            recent = (served['service_date'] >= start) & (served['service_date'] < d)
            out[d] = set(matching) if bool(recent.any()) else set()
        return out

    def recent_week_signatures(
        self,
        week_start: dt.date,
        cooldown_days: int = 30,
    ) -> Set[str]:
        """Return week signatures within the cooldown window."""
        h = self._weeks
        if h is None:
            return set()
        start = week_start - dt.timedelta(days=cooldown_days)
        mask = (h['week_start'] >= start) & (h['week_start'] < week_start)
        return set(h.loc[mask, 'week_signature'].tolist())

    def ricebread_ban_by_date(
        self,
        dates: List[dt.date],
        ricebread_items: Set[str],
        gap_days: int = 10,
        base_slot_fn=None,
    ) -> Dict[dt.date, bool]:
        """Return per-date flag if rice-bread was used too recently."""
        h = self._long
        if h is None or gap_days <= 0 or not ricebread_items:
            return {d: False for d in dates}
        out: Dict[dt.date, bool] = {}
        for d in dates:
            start = d - dt.timedelta(days=gap_days)
            m = (h['service_date'] >= start) & (h['service_date'] < d)
            if 'slot' in h.columns:
                if base_slot_fn is None:
                    m &= h['slot'] == 'bread'
                else:
                    m &= h['slot'].map(base_slot_fn) == 'bread'
            m &= h['item_base'].isin(ricebread_items)
            out[d] = bool(m.any())
        return out

    # ----- Save -----

    def save(
        self,
        week_plan: Dict,
        dates: List[dt.date],
        client_name: str,
        week_start: dt.date,
        week_signature: str,
        supabase_client,
        strip_color_fn=None,
    ):
        """Persist a completed week plan to Supabase with **overwrite**
        semantics.

        Storage: one row per (client, service_date) in ``menu_history``,
        with the day's whole menu in a ``menu`` JSONB column
        (``{slot: item_base}``) — not one row per dish. Re-saving a plan
        for the same (client, dates) replaces those day rows (DELETE then
        INSERT, since the primary key is ``(client_name, service_date)``).
        The ``week_signatures`` row is overwritten the same way, keyed by
        ``(client_name, week_start)``.
        """
        if supabase_client is None:
            raise ValueError("supabase_client is required to save history.")

        # One JSONB row per date. Empty days are skipped so "partially
        # saved" ranges stay distinguishable from fully-saved ones.
        day_rows = []
        for d in dates:
            day_map = week_plan.get(d, {})
            menu = {}
            for slot_id, item_val in day_map.items():
                item_base = strip_color_fn(item_val) if strip_color_fn else item_val
                item_base = _norm_str(item_base)
                if item_base:
                    menu[slot_id] = item_base
            if menu:
                day_rows.append({
                    'client_name': client_name,
                    'service_date': d.isoformat(),
                    'menu': menu,
                })

        date_isos = [d.isoformat() for d in dates]
        if date_isos:
            (
                supabase_client.table('menu_history')
                .delete()
                .eq('client_name', client_name)
                .in_('service_date', date_isos)
                .execute()
            )
        if day_rows:
            supabase_client.table('menu_history').insert(day_rows).execute()

        # Same overwrite rule for the per-week signature row.
        (
            supabase_client.table('week_signatures')
            .delete()
            .eq('client_name', client_name)
            .eq('week_start', week_start.isoformat())
            .execute()
        )
        supabase_client.table('week_signatures').insert({
            'week_start': week_start.isoformat(),
            'week_signature': week_signature,
            'client_name': client_name,
        }).execute()

    def save_counters(
        self,
        counter_plans,
        dates: List[dt.date],
        client_name: str,
        week_start: dt.date,
        week_signature: str,
        supabase_client,
        strip_color_fn=None,
    ):
        """Persist a multi-cuisine week: one ``menu_history`` row per day with
        a **nested** menu ``{counter_name: {slot: item_base}}``.

        ``counter_plans`` is a list of ``(counter_name, week_plan)`` where each
        ``week_plan`` is ``{date: {slot: item}}``. Overwrite semantics + the
        single week-signature row match :meth:`save`.
        """
        if supabase_client is None:
            raise ValueError("supabase_client is required to save history.")

        day_rows = []
        for d in dates:
            day_menu = {}
            for cname, wp in counter_plans:
                menu = {}
                for slot_id, item_val in (wp.get(d, {}) or {}).items():
                    item_base = strip_color_fn(item_val) if strip_color_fn else item_val
                    item_base = _norm_str(item_base)
                    if item_base:
                        menu[slot_id] = item_base
                if menu:
                    day_menu[cname] = menu
            if day_menu:
                day_rows.append({
                    'client_name': client_name,
                    'service_date': d.isoformat(),
                    'menu': day_menu,
                })

        date_isos = [d.isoformat() for d in dates]
        if date_isos:
            (
                supabase_client.table('menu_history')
                .delete()
                .eq('client_name', client_name)
                .in_('service_date', date_isos)
                .execute()
            )
        if day_rows:
            supabase_client.table('menu_history').insert(day_rows).execute()

        (
            supabase_client.table('week_signatures')
            .delete()
            .eq('client_name', client_name)
            .eq('week_start', week_start.isoformat())
            .execute()
        )
        supabase_client.table('week_signatures').insert({
            'week_start': week_start.isoformat(),
            'week_signature': week_signature,
            'client_name': client_name,
        }).execute()

    # ----- Load saved plan -----

    @staticmethod
    def load_saved_plan(
        supabase_client,
        client_name: str,
        dates: List[dt.date],
    ) -> Dict[dt.date, Dict[str, str]]:
        """Return the saved menu for *client_name* across *dates*.

        Result shape: ``{date: {slot_id: item_base}}``, read straight from
        the ``menu`` JSONB column (one row per day, PK on
        ``(client_name, service_date)``). Only dates with a non-empty menu
        are present, so callers distinguish "fully saved" (all requested
        dates present) from "partial" / "not saved".

        ``item_base`` is the de-colorised name we persisted; the caller
        re-attaches a color suffix for display (``_enrich_history_plan``).
        """
        if supabase_client is None:
            raise ValueError("supabase_client is required to load history.")
        if not dates:
            return {}

        date_isos = [d.isoformat() for d in dates]
        resp = (
            supabase_client.table('menu_history')
            .select('service_date, menu')
            .eq('client_name', client_name)
            .in_('service_date', date_isos)
            .execute()
        )
        rows = resp.data or []

        out: Dict[dt.date, Dict[str, str]] = {}
        for r in rows:
            iso = r.get('service_date')
            menu = r.get('menu')
            if not iso or not isinstance(menu, dict) or not menu:
                continue
            try:
                d = dt.date.fromisoformat(iso)
            except (TypeError, ValueError):
                continue
            out[d] = {slot: (item or '') for slot, item in menu.items()}
        return out

    # ----- Explode JSONB day rows into the long (per-item) form -----

    @staticmethod
    def explode_history_rows(rows: Optional[List[Dict]]) -> Optional[pd.DataFrame]:
        """Turn ``menu_history`` day rows (``{client_name, service_date,
        menu:{slot:item}}``) into the long ``(client_name, service_date,
        slot, item_base)`` DataFrame the cooldown readers expect.

        Returns None for empty input so ``load_from_dataframes`` treats it
        as "no history".
        """
        long_rows: List[Dict] = []
        for r in rows or []:
            menu = r.get('menu')
            if not isinstance(menu, dict):
                continue
            cn = r.get('client_name')
            sd = r.get('service_date')
            for key, val in menu.items():
                if isinstance(val, dict):
                    # nested (multi-cuisine): key=counter, val={slot: item}
                    for slot, item in val.items():
                        long_rows.append({
                            'client_name': cn, 'service_date': sd,
                            'slot': slot, 'item_base': item,
                        })
                else:
                    # flat (single-cuisine): key=slot, val=item
                    long_rows.append({
                        'client_name': cn, 'service_date': sd,
                        'slot': key, 'item_base': val,
                    })
        return pd.DataFrame(long_rows) if long_rows else None

    # ----- Signature computation -----

    @staticmethod
    def compute_week_signature(
        week_plan: Dict,
        dates: List[dt.date],
        const_slots: List[str] = (),
        strip_color_fn=None,
    ) -> str:
        """Compute a deterministic signature string for a week plan."""
        const_set = set(const_slots)

        # Infer slot order from the first non-empty day
        slot_order: List[str] = []
        for d in dates:
            day_map = week_plan.get(d, {})
            if day_map:
                slot_order = [k for k in day_map.keys() if k not in const_set]
                break

        parts: List[str] = []
        for d in dates:
            parts.append(d.isoformat())
            day_map = week_plan.get(d, {})
            for slot_id in slot_order:
                val = day_map.get(slot_id, '')
                if strip_color_fn:
                    val = strip_color_fn(val)
                parts.append(f'{slot_id}={_norm_str(val)}')
        return '|'.join(parts)

    # ----- Signature parsing -----

    @staticmethod
    def parse_signature_to_expected_map(sig: str) -> Dict:
        """Parse a week signature into {(date_iso, slot): item_base} map."""
        parts = sig.split('|')
        out: Dict = {}
        i = 0
        while i < len(parts):
            token = parts[i]
            if re.match(r'^\d{4}-\d{2}-\d{2}$', token):
                date_iso = token
                i += 1
                while i < len(parts) and not re.match(r'^\d{4}-\d{2}-\d{2}$', parts[i]):
                    kv = parts[i]
                    if '=' in kv:
                        slot, val = kv.split('=', 1)
                        out[(date_iso, _norm_str(slot))] = _norm_str(val)
                    i += 1
            else:
                i += 1
        return out
