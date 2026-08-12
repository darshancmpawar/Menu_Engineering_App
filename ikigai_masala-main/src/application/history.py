"""Assembling the cooldown context a solve needs from saved history.

Lifted out of `api/app.py`. Reads history through `HistoryManager` and returns
the banned-item and rice-bread maps the rules consume; the widened query window
lives here too, because how far back to look follows from the cooldown rules
rather than from anything about the request.
"""

from __future__ import annotations

import datetime as dt

from src.constants import CONST_SLOTS, REPEATABLE_ITEM_BASES
from src.history.history_manager import HistoryManager

#: How far back the history query reaches by default, and the slack added on top
#: so a per-client cooldown override longer than the default still sees the rows
#: it needs. Defined here rather than in api/config: both numbers follow from the
#: cooldown rules, not from HTTP.
_HISTORY_WINDOW_DAYS = 45
_HISTORY_WINDOW_SLACK_DAYS = 15


def _build_history_context(
    df, client_name, start_date, weekday_dates, window_days=None,
    cooldown_days=None, selector_windows=None,
):
    """Shared helper to build history-based solver inputs from Supabase.

    Pushes ``client_name`` and ``service_date >= cutoff`` filters down to
    Supabase so the query hits the ``(client_name, service_date DESC)``
    index on ``menu_history`` (and the analogous index on
    ``week_signatures``) instead of scanning every row for every tenant.

    *window_days* is the backward-lookback in days. Callers should pass
    ``_effective_history_window(rules)`` so per-client rule overrides
    don't silently truncate the window. Falling back to the floor
    keeps the function usable in tests / scripts that don't assemble
    rules upfront.
    """
    import pandas as pd
    from src.db import get_supabase

    if window_days is None:
        window_days = _HISTORY_WINDOW_DAYS
    earliest = start_date - dt.timedelta(days=window_days)
    earliest_iso = earliest.isoformat()

    hm = HistoryManager()
    sb = get_supabase()
    long_resp = (
        sb.table('menu_history')
        .select('*')
        .eq('client_name', client_name)
        .gte('service_date', earliest_iso)
        .execute()
    )
    weeks_resp = (
        sb.table('week_signatures')
        .select('*')
        .eq('client_name', client_name)
        .gte('week_start', earliest_iso)
        .execute()
    )
    # menu_history stores one JSONB row per (client, date); explode it into
    # the long per-item form the cooldown readers consume.
    long_df = HistoryManager.explode_history_rows(long_resp.data)
    weeks_df = pd.DataFrame(weeks_resp.data) if weeks_resp.data else None
    hm.load_from_dataframes(long_df, weeks_df)
    # Rows are already scoped to this client at the DB layer, but leave
    # the in-memory filter in place as belt-and-suspenders for anyone
    # who seeds the manager from an unfiltered DataFrame.
    hm = hm.filter_by_client(client_name)

    _cooldown_kw = {} if cooldown_days is None else {'cooldown_days': int(cooldown_days)}
    banned = hm.banned_items_by_date(weekday_dates, const_slots=CONST_SLOTS,
                                      repeatable_items=REPEATABLE_ITEM_BASES,
                                      **_cooldown_kw)
    # Cross-week selector cadences ("fish once per 15 days"): ban the whole
    # selector on dates within its window of a saved occurrence, folded into
    # the same per-date ban map the item-cooldown pre-filter already applies.
    for matching_items, sel_window in (selector_windows or []):
        sel_bans = hm.selector_banned_by_date(
            weekday_dates, matching_items, sel_window)
        for d, items in sel_bans.items():
            if items:
                banned.setdefault(d, set()).update(items)
    ricebread_items = set(
        df.loc[df.get('is_rice_bread', 0) == 1, 'item'].tolist()
    ) if 'is_rice_bread' in df.columns else set()
    rb_ban = hm.ricebread_ban_by_date(weekday_dates, ricebread_items)
    recent_sigs = hm.recent_week_signatures(start_date)
    return banned, rb_ban, recent_sigs
