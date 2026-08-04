"""Which dates and which slots a plan actually covers.

Pure date arithmetic lifted out of `api/app.py`: weekday expansion, the
`serve_weekends` switch, the per-client `working_days` filter, and the base slots
a counter runs. No Flask, no database — a request hands these functions plain
values.
"""

from __future__ import annotations

import datetime as dt

from src.constants import CONST_SLOTS
from src.preprocessor.pool_builder import _base_slot


def _weekdays_from(start_date, num_days, serve_weekends=False):
    """Return ``num_days`` service dates starting from ``start_date``.

    By default Sat/Sun are skipped (weekday-only kitchens). When
    ``serve_weekends`` is True every calendar day counts, so the plan can
    cover Saturday and Sunday (e.g. a 6-day plan from Monday = Mon–Sat).
    """
    dates = []
    d = start_date
    while len(dates) < num_days:
        if serve_weekends or d.weekday() < 5:  # Mon-Fri, or all days
            dates.append(d)
        d += dt.timedelta(days=1)
    return dates


def _filter_dates_by_working_days(dates, working_days):
    """Keep only dates whose weekday is in *working_days* (None = unchanged)."""
    if not working_days:
        return list(dates)
    from src.solver.menu_solver import _WEEKDAY_ALIASES
    from src.solver._helpers import weekday_name
    allowed = {
        _WEEKDAY_ALIASES.get(str(d).strip().lower(), str(d).strip().lower())
        for d in working_days
    }
    return [d for d in dates if weekday_name(d) in allowed]


def _client_base_slots(client_cfg):
    """Return unique base slot names the client uses (excluding constants).

    Handles expanded slot IDs like veg_dry__1, veg_dry__2 by extracting
    the base name so the solver gets ['veg_dry'] not ['veg_dry__1', 'veg_dry__2'].
    """
    seen = set()
    result = []
    for s in client_cfg.active_slots:
        if s in CONST_SLOTS:
            continue
        base = _base_slot(s)
        if base not in seen:
            seen.add(base)
            result.append(base)
    return result
