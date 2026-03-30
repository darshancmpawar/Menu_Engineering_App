from __future__ import annotations

import datetime as dt
import re
from typing import Optional

import pandas as pd


def _norm_str(x) -> str:
    if pd.isna(x):
        return ''
    return str(x).strip().lower()


def ensure_history_long(history_long_df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    if history_long_df is None or len(history_long_df) == 0:
        return None
    h = history_long_df.copy()
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


def ensure_history_weeks(history_weeks_df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    if history_weeks_df is None or len(history_weeks_df) == 0:
        return None
    h = history_weeks_df.copy()
    if 'week_start' not in h.columns or 'week_signature' not in h.columns:
        return None
    h['week_start'] = pd.to_datetime(h['week_start'], errors='coerce').dt.date
    h['week_signature'] = h['week_signature'].astype(str)
    if 'client_name' in h.columns:
        h['client_name'] = h['client_name'].map(_norm_str)
    h = h[h['week_start'].notna()]
    return h


def filter_history_by_client(history_long_df, history_weeks_df, client_name):
    c = _norm_str(client_name) if client_name else ''
    hl, hw = (ensure_history_long(history_long_df), ensure_history_weeks(history_weeks_df))
    if not c:
        return (hl, hw)
    if hl is not None and 'client_name' in hl.columns:
        hl = hl[hl['client_name'] == c]
    if hw is not None and 'client_name' in hw.columns:
        hw = hw[hw['client_name'] == c]
    return (hl, hw)


def banned_items_by_date(history_long_df, dates, item_cooldown_days=20, const_slots=(), repeatable_item_bases=()):
    h = ensure_history_long(history_long_df)
    if h is None:
        return {d: set() for d in dates}
    out, const_set = ({}, set(const_slots))
    for d in dates:
        start = d - dt.timedelta(days=item_cooldown_days)
        m = (h['service_date'] >= start) & (h['service_date'] < d)
        if 'slot' in h.columns:
            m &= ~h['slot'].isin(const_set)
        banned = set(h.loc[m, 'item_base'].tolist()) - set(repeatable_item_bases)
        out[d] = banned
    return out


def recent_week_signatures(history_weeks_df, week_start, menu_cooldown_days=30):
    h = ensure_history_weeks(history_weeks_df)
    if h is None:
        return set()
    start = week_start - dt.timedelta(days=menu_cooldown_days)
    return set(h.loc[(h['week_start'] >= start) & (h['week_start'] < week_start), 'week_signature'].tolist())


def ricebread_ban_by_date(history_long_df, dates, ricebread_items, rice_bread_gap_days=10, base_slot_fn=None):
    h = ensure_history_long(history_long_df)
    if h is None or rice_bread_gap_days <= 0 or (not ricebread_items):
        return {d: False for d in dates}
    out = {}
    for d in dates:
        start = d - dt.timedelta(days=rice_bread_gap_days)
        m = (h['service_date'] >= start) & (h['service_date'] < d)
        if 'slot' in h.columns:
            if base_slot_fn is None:
                m &= h['slot'] == 'bread'
            else:
                m &= h['slot'].map(base_slot_fn) == 'bread'
        m &= h['item_base'].isin(ricebread_items)
        out[d] = bool(m.any())
    return out


def parse_signature_to_expected_map(sig):
    parts, out, i = (sig.split('|'), {}, 0)
    while i < len(parts):
        token = parts[i]
        if re.match('^\\d{4}-\\d{2}-\\d{2}$', token):
            date_iso = token
            i += 1
            while i < len(parts) and (not re.match('^\\d{4}-\\d{2}-\\d{2}$', parts[i])):
                kv = parts[i]
                if '=' in kv:
                    slot, val = kv.split('=', 1)
                    out[date_iso, _norm_str(slot)] = _norm_str(val)
                i += 1
        else:
            i += 1
    return out


def add_week_signature_cooldown_constraints(model, cells, recent_sigs):
    for sig in recent_sigs:
        exp, lits = (parse_signature_to_expected_map(sig), [])
        for cell in cells:
            want = exp.get((cell.date.isoformat(), _norm_str(cell.slot_id)))
            if not want:
                lits = []
                break
            found = None
            for var, row in zip(cell.x_vars, cell.cand_rows):
                if _norm_str(row.get('item', '')) == want:
                    found = var
                    break
            if found is None:
                lits = []
                break
            lits.append(found)
        if lits and len(lits) >= 2:
            model.Add(sum(lits) <= len(lits) - 1)
