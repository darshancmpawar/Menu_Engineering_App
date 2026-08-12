"""
Client configuration loader — Supabase backend.

Every read queries Supabase directly so any change made via the UI, API, or
dashboard is immediately reflected on the next call.

Schema (consolidated — the whole config is one document per client):
    clients   (name TEXT PK, version INT, counters JSONB, created_at)
    app_settings (key, value)

``clients.counters`` is the single source of truth for a client's cuisine
setup — an ordered, non-empty list of counters::

    [{name, categories, slot_counts, theme_map}, …]

``counters[0]`` is the *primary* counter, the one the menu solver plans from;
``counters[1:]`` are additional stations for a multi-cuisine client. The mode
is derived: single ⇔ one counter, multi ⇔ two or more. The legacy
``menu_categories`` / ``slot_count_overrides`` / ``theme_overrides`` tables
have been folded into this column (see scripts/setup_all.sql); the loader
still reads them as a one-time fallback for a database that hasn't run the
migration yet.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from src.constants import (
    BASE_SLOT_NAMES as BASE_SLOTS,
    CONST_SLOTS,
    DEFAULT_OFF_SLOTS,
    DEFAULT_WEEKDAY_THEMES,
    MUTUALLY_EXCLUSIVE_SLOT_GROUPS,
    DISPLAY_SLOT_NAME,
)
from src.db import get_supabase
from src.preprocessor.pool_builder import _expand_slots_in_order
from src.preprocessor.client_pool_filter import (
    normalize_name as _normalize_pool_name, COMMON_POOL,
)

logger = logging.getLogger(__name__)


# Postgres "undefined_column" / "undefined_table" codes, plus the PostgREST
# wrappers (PGRST204 unknown column, PGRST205 unknown table). Detecting these
# lets the loader degrade gracefully when a deployment hasn't applied the
# latest migration yet.
_PG_UNDEFINED_COLUMN = "42703"
_PG_UNDEFINED_TABLE = "42P01"
_MIGRATION_HINT = (
    "Re-run scripts/setup_all.sql in the Supabase SQL editor to apply the "
    "latest schema. Optimistic-concurrency on PUT /client-config is degraded "
    "until the clients.version column exists."
)
_MIGRATION_HINT_COUNTERS = (
    "Re-run scripts/setup_all.sql in the Supabase SQL editor to add the "
    "clients.counters JSONB column. Client config falls back to the legacy "
    "tables until the migration is applied."
)


def _is_undefined_column(exc: BaseException) -> bool:
    """Return True if *exc* looks like a Postgres undefined-column error."""
    if getattr(exc, "code", None) == _PG_UNDEFINED_COLUMN:
        return True
    msg = str(exc).lower()
    return "does not exist" in msg and "column" in msg


def _is_missing_relation(exc: BaseException) -> bool:
    """Return True if *exc* looks like a missing table / column / schema-cache
    error — i.e. a migration hasn't been applied yet."""
    code = getattr(exc, "code", None)
    if code in (_PG_UNDEFINED_COLUMN, _PG_UNDEFINED_TABLE, "PGRST205", "PGRST204"):
        return True
    msg = str(exc).lower()
    return (
        "does not exist" in msg
        or "could not find" in msg
        or "schema cache" in msg
    )


# Per-client default day themes — the same Mon..Fri mapping the solver falls
# back to; kept as a dict copy so callers can mutate their own theme_map.
DEFAULT_THEME_MAP: Dict[str, str] = dict(DEFAULT_WEEKDAY_THEMES)

AVAILABLE_THEMES: List[str] = [
    'mix', 'chinese', 'biryani', 'south', 'north', 'continental',
    # Weekly-alternating meta-theme: even ISO week → chinese, odd → continental.
    'chinese_continental',
]

# Cities a client can be located in. A client's ``city`` is a plain column on
# the ``clients`` row (not per-counter). ``None``/empty means "unset".
AVAILABLE_CITIES: List[str] = ['Bangalore', 'Pune', 'Chennai', 'Hyderabad', 'NCR']

# Default item-cooldown window (days): an item served within this many days
# before a date is banned from that date. Mirrors the shipped
# ``item_cooldown_20d`` rule / ``banned_items_by_date`` default. Per-client
# overridable via the ``clients.item_cooldown_days`` column (None = default).
DEFAULT_ITEM_COOLDOWN_DAYS: int = 20
_MAX_ITEM_COOLDOWN_DAYS: int = 60


def normalize_item_cooldown_days(value) -> Optional[int]:
    """Coerce a cooldown-days input to an int in [0, 60], or None if unset."""
    if value is None or value == '':
        return None
    try:
        v = int(value)
    except (TypeError, ValueError):
        return None
    return max(0, min(_MAX_ITEM_COOLDOWN_DAYS, v))


def normalize_city(value: Optional[str]) -> Optional[str]:
    """Return a canonical city from ``AVAILABLE_CITIES`` or ``None``.

    Matching is case-insensitive so ``'bangalore'`` resolves to ``'Bangalore'``.
    Any unknown / blank value normalises to ``None`` (unset).
    """
    if not value:
        return None
    v = str(value).strip().lower()
    for city in AVAILABLE_CITIES:
        if city.lower() == v:
            return city
    return None


class ConcurrentEditError(ValueError):
    """Raised when an optimistic-concurrency version check fails.

    The ``current_version`` attribute carries the version that's actually in
    the database right now so callers can surface it (e.g. in a 409 response
    body) and the client can refresh + retry.
    """

    def __init__(self, message: str, *, current_version: int | None = None):
        super().__init__(message)
        self.current_version = current_version


@dataclass
class ClientConfig:
    name: str
    active_slots: List[str] = field(default_factory=list)
    slot_counts: Dict[str, int] = field(default_factory=dict)
    theme_map: Dict[str, str] = field(default_factory=dict)
    # Client-level (not per-counter): when True the planner also covers
    # Saturday/Sunday instead of skipping them.
    serve_weekends: bool = False
    # Client-level: restrict generation to these weekdays only (lowercase full
    # names, e.g. ['wednesday','thursday','friday']). None => all weekdays.
    working_days: Optional[List[str]] = None
    # Which counter of the client this config came from. Lets per-counter rule
    # overrides in client_rules.json be scoped to one station.
    counter_name: Optional[str] = None


def _dedupe_preserve_order(values: List[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for v in values:
        if v not in seen:
            out.append(v)
            seen.add(v)
    return out


# ---------------------------------------------------------------------------
# Counter helpers
# ---------------------------------------------------------------------------
# A "counter" is the config for one cuisine station: which food categories it
# serves, how many of each (frequency), and the per-weekday theme. Canonical
# in-memory shape:
#     {'name': str, 'categories': [slot],
#      'slot_counts': {slot: int}, 'theme_map': {day: theme}}

# Frequency bounds mirror the editor's number_input (1..5 per category).
# The ceiling was 3, which made a real counter unconfigurable: a non-veg lunch
# station serving biryani + gravy + dry + kebab + egg needs 5 nonveg_main slots,
# and the editor rejected the value with "outside the allowed range" instead.
_MIN_SLOT_COUNT = 1
_MAX_SLOT_COUNT = 5
# Hard cap on counters per client — keeps the editor UI and payloads sane.
MAX_COUNTERS = 6

# Categories a fresh client gets by default: every base slot except the
# constants and the opt-in (default-off) stations like curd_rice.
_TOGGLEABLE_BASE_SLOTS: List[str] = [
    s for s in BASE_SLOTS if s not in CONST_SLOTS and s not in DEFAULT_OFF_SLOTS
]


def default_counter(index: int = 0, name: str = "") -> Dict:
    """Return a fresh counter config with sensible defaults.

    Defaults to every (non-constant) category active at frequency 1 and the
    global default day themes.
    """
    return {
        'name': name or f'Counter {index + 1}',
        'categories': list(_TOGGLEABLE_BASE_SLOTS),
        'slot_counts': {s: 1 for s in _TOGGLEABLE_BASE_SLOTS},
        'theme_map': dict(DEFAULT_THEME_MAP),
    }


def normalize_counter(raw: Dict, index: int = 0) -> Dict:
    """Coerce arbitrary/partial counter input into the canonical shape.

    - drops unknown / constant slots from ``categories`` (dedup, order-preserving)
    - clamps every ``slot_counts`` value to [1, 5]; only keeps active categories
    - merges ``theme_map`` over the global defaults, ignoring invalid days/themes
    - falls back to ``Counter N`` for a blank name
    """
    raw = raw or {}
    name = str(raw.get('name') or '').strip() or f'Counter {index + 1}'

    # Categories may be base slots or constant slots (white_rice / papad /
    # pickle / chutney) — the latter are per-client selectable, not forced.
    valid = set(BASE_SLOTS) | set(CONST_SLOTS)
    cats = _dedupe_preserve_order([
        c for c in (raw.get('categories') or []) if c in valid
    ])

    raw_counts = raw.get('slot_counts') or {}
    slot_counts: Dict[str, int] = {}
    for c in cats:
        if c in CONST_SLOTS:
            continue  # constant items are single fixed dishes — no frequency
        try:
            v = int(raw_counts.get(c, 1))
        except (TypeError, ValueError):
            v = 1
        slot_counts[c] = max(_MIN_SLOT_COUNT, min(_MAX_SLOT_COUNT, v))

    theme_map = dict(DEFAULT_THEME_MAP)
    for day, theme in (raw.get('theme_map') or {}).items():
        d = str(day).lower()
        if d in theme_map and theme in AVAILABLE_THEMES:
            theme_map[d] = theme

    return {
        'name': name,
        'categories': cats,
        'slot_counts': slot_counts,
        'theme_map': theme_map,
    }


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

class ClientConfigLoader:
    """Loads client configuration from Supabase.

    Every method issues a live query — there is no in-memory cache, so data is
    always consistent with the database.
    """

    def __init__(self, config_path: str = ''):
        self._sb = get_supabase()

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

    def list_clients_with_city(self) -> List[Dict]:
        """Return ``[{'name', 'city', 'is_launch_site'}, …]``, sorted by name.

        Feeds the sidebar's city + launch-site filters. Degrades to
        ``city=None, is_launch_site=False`` for every client when the columns are
        missing (pre-migration database) — one retry drops ``is_launch_site`` so
        a database that has ``city`` but not the newer flag still works.
        """
        for cols in ('name, city, is_launch_site', 'name, city'):
            try:
                rows = (
                    self._sb.table('clients').select(cols).order('name').execute()
                )
                break
            except Exception as exc:
                if _is_missing_relation(exc):
                    return [{'name': n, 'city': None, 'is_launch_site': False}
                            for n in self.client_names]
                if cols != 'name, city':      # missing is_launch_site → retry
                    continue
                raise
        return [
            {'name': r['name'], 'city': normalize_city(r.get('city')),
             'is_launch_site': bool(r.get('is_launch_site'))}
            for r in rows.data
        ]

    @property
    def core_min_one_slots(self) -> List[str]:
        val = self._setting('core_min_one_slots')
        return val if val else []

    @property
    def constant_slots(self) -> List[str]:
        val = self._setting('constant_slots')
        return val if val else list(CONST_SLOTS)

    # ---- counter source (single source of truth) --------------------------

    def _read_counters_column(self, name: str) -> List[Dict]:
        """Return the raw ``clients.counters`` list for a client.

        Raises ValueError for an unknown client. Returns ``[]`` (and logs)
        when the column is missing (pre-migration deployment) so the caller
        can fall back to the legacy tables.
        """
        try:
            row = (
                self._sb.table('clients')
                .select('counters')
                .eq('name', name)
                .maybe_single()
                .execute()
            )
        except Exception as exc:
            if _is_missing_relation(exc):
                logger.error(
                    "clients.counters missing for %r — %s",
                    name, _MIGRATION_HINT_COUNTERS,
                )
                self._require_client_exists(name)
                return []
            raise
        if not row.data:
            raise ValueError(f"Unknown client: {name}")
        stored = row.data.get('counters')
        return stored if isinstance(stored, list) else []

    def _counters_list(self, name: str) -> List[Dict]:
        """Return the client's counters, normalised and always non-empty.

        Prefers ``clients.counters``; if empty (a client created before the
        migration, or a not-yet-migrated database) it falls back to the legacy
        config tables, and finally to an all-categories default.
        """
        raw = self._read_counters_column(name)
        if raw:
            return [normalize_counter(c, i) for i, c in enumerate(raw)]
        legacy = self._legacy_primary_counter(name)
        return [legacy] if legacy else [default_counter(0)]

    def _legacy_primary_counter(self, name: str) -> Optional[Dict]:
        """Build one counter from the pre-migration config tables.

        Returns None when those tables/columns no longer exist (post-migration)
        or the client has no legacy config. Fully guarded so it never breaks a
        migrated database.
        """
        try:
            cat_row = (
                self._sb.table('clients')
                .select('menu_category')
                .eq('name', name)
                .maybe_single()
                .execute()
            )
            cat = (cat_row.data or {}).get('menu_category') if cat_row.data else None
            if not cat:
                return None
            slots_row = (
                self._sb.table('menu_categories')
                .select('slots')
                .eq('name', cat)
                .maybe_single()
                .execute()
            )
            slots = (slots_row.data or {}).get('slots') if slots_row.data else None
            if not slots:
                return None
            sc = (
                self._sb.table('slot_count_overrides')
                .select('slot, count')
                .eq('client_name', name)
                .execute()
            )
            counts = {r['slot']: r['count'] for r in (sc.data or [])}
            th = (
                self._sb.table('theme_overrides')
                .select('day, theme')
                .eq('client_name', name)
                .execute()
            )
            themes = {r['day']: r['theme'] for r in (th.data or [])}
        except Exception as exc:
            if _is_missing_relation(exc):
                return None
            raise
        return normalize_counter({
            'name': 'Counter 1',
            'categories': slots,
            'slot_counts': counts,
            'theme_map': themes,
        }, 0)

    # ---- client read methods -----------------------------------------------

    def _config_from_counter(self, name: str, counter: Dict) -> ClientConfig:
        """Build a ClientConfig for one (normalized) counter — the shape the
        solver consumes. Shared by the primary-counter path (get_client) and
        the per-counter path (get_client_configs)."""
        counts = {s: 1 for s in BASE_SLOTS}
        for slot, cnt in (counter.get('slot_counts') or {}).items():
            if slot in counts:
                counts[slot] = max(0, int(cnt))
        for must in self.core_min_one_slots:
            counts[must] = max(1, int(counts.get(must, 1)))

        expanded: List[str] = []
        for slot in counter.get('categories') or []:
            if slot in CONST_SLOTS:
                expanded.append(slot)
            else:
                expanded.extend(
                    _expand_slots_in_order([slot], {slot: counts.get(slot, 1)})
                )
        expanded = _dedupe_preserve_order(expanded)

        return ClientConfig(
            name=name,
            active_slots=expanded,
            slot_counts=counts,
            theme_map=dict(counter.get('theme_map') or DEFAULT_THEME_MAP),
            counter_name=counter.get('name'),
        )

    def get_client(self, name: str) -> ClientConfig:
        """Return a ClientConfig sourced from the primary counter
        (``counters[0]``). Output shape is unchanged, so the solver is
        unaffected."""
        cfg = self._config_from_counter(name, self._counters_list(name)[0])
        cfg.serve_weekends = self.get_client_serve_weekends(name)
        cfg.working_days = self.get_client_working_days(name)
        return cfg

    def get_client_configs(self, name: str):
        """Return ``[(counter_name, ClientConfig), …]`` — one per counter.

        Single-cuisine clients yield a one-element list; multi-cuisine clients
        yield one config per counter, each with that counter's categories /
        frequency / day-themes for an independent solve. The client-level
        ``serve_weekends`` flag is stamped onto every counter's config.
        """
        serve_weekends = self.get_client_serve_weekends(name)
        working_days = self.get_client_working_days(name)
        out = []
        for c in self._counters_list(name):
            cfg = self._config_from_counter(name, c)
            cfg.serve_weekends = serve_weekends
            cfg.working_days = working_days
            out.append((c['name'], cfg))
        return out

    def get_counters_for_client(self, name: str) -> List[Dict]:
        """Return the ordered, normalised list of counter configs (>=1)."""
        return self._counters_list(name)

    def get_counter_setup(self, name: str):
        """Return ``(mode, counters)`` in a single ``clients.counters`` read."""
        counters = self._counters_list(name)
        mode = 'multi' if len(counters) >= 2 else 'single'
        return mode, counters

    def get_counter_mode(self, name: str) -> str:
        """Return 'single' or 'multi', derived from the counter count."""
        return self.get_counter_setup(name)[0]

    def get_client_city(self, name: str) -> Optional[str]:
        """Return the client's city (or ``None`` if unset / pre-migration).

        Degrades gracefully to ``None`` when the ``clients.city`` column is
        missing so an un-migrated database keeps working.
        """
        try:
            row = (
                self._sb.table('clients')
                .select('city')
                .eq('name', name)
                .maybe_single()
                .execute()
            )
        except Exception as exc:
            if _is_missing_relation(exc):
                return None
            raise
        if not row.data:
            raise ValueError(f"Unknown client: {name}")
        return normalize_city(row.data.get('city'))

    def get_client_source_pools(self, name: str):
        """Return the client's configured extra item pools (F5).

          * ``list`` — configured pool tokens (``common`` is always implied and
            is never stored here).
          * ``[]``   — column exists but this client has none configured, so
            its eligible pool is common-only.
          * ``None`` — the ``clients.source_pools`` column is missing
            (pre-migration). Callers fall back to the full ontology so an
            un-migrated database keeps working unchanged.
        """
        try:
            row = (
                self._sb.table('clients')
                .select('source_pools')
                .eq('name', name)
                .maybe_single()
                .execute()
            )
        except Exception as exc:
            if _is_missing_relation(exc):
                return None
            raise
        if not row.data:
            raise ValueError(f"Unknown client: {name}")
        val = row.data.get('source_pools')
        if val is None:
            return []
        return [_normalize_pool_name(t) for t in val if _normalize_pool_name(t)]

    def get_client_shared_categories(self, name: str):
        """Return the base slots this client serves identically across counters.

          * ``list`` — configured base slots (the planner pins the primary
            counter's dish for each into the others per day).
          * ``[]``   — column exists but this client shares nothing.
          * ``None`` — the ``clients.shared_categories`` column is missing
            (pre-migration). Callers fall back to the file-based value in
            ``client_rules.json`` so an un-migrated database keeps working.
        """
        try:
            row = (
                self._sb.table('clients')
                .select('shared_categories')
                .eq('name', name)
                .maybe_single()
                .execute()
            )
        except Exception as exc:
            if _is_missing_relation(exc):
                return None
            raise
        if not row.data:
            raise ValueError(f"Unknown client: {name}")
        return self._normalize_shared_categories_value(
            row.data.get('shared_categories'))

    def get_client_serve_weekends(self, name: str) -> bool:
        """Return whether the client is served on weekends (Sat/Sun).

        Degrades to ``False`` when the ``clients.serve_weekends`` column is
        missing (pre-migration database)."""
        try:
            row = (
                self._sb.table('clients')
                .select('serve_weekends')
                .eq('name', name)
                .maybe_single()
                .execute()
            )
        except Exception as exc:
            if _is_missing_relation(exc):
                return False
            raise
        if not row.data:
            raise ValueError(f"Unknown client: {name}")
        return bool(row.data.get('serve_weekends'))

    def set_client_serve_weekends(self, name: str, value: bool) -> None:
        """Update a client's weekend-service flag."""
        self._require_client_exists(name)
        try:
            self._sb.table('clients').update({
                'serve_weekends': bool(value),
            }).eq('name', name).execute()
        except Exception as exc:
            if _is_missing_relation(exc):
                logger.error(
                    "clients.serve_weekends column missing for %r — %s",
                    name, _MIGRATION_HINT_COUNTERS,
                )
                raise ValueError(
                    "Cannot save weekend setting: the clients.serve_weekends "
                    "column is missing. " + _MIGRATION_HINT_COUNTERS
                ) from exc
            raise

    def get_client_is_launch_site(self, name: str) -> bool:
        """Return whether the client is a launch site (F: launch view).

        Degrades to ``False`` when the ``clients.is_launch_site`` column is
        missing (pre-migration database) — i.e. nothing is a launch site until
        the column exists, which matches "every existing client is non-launch"."""
        try:
            row = (
                self._sb.table('clients')
                .select('is_launch_site')
                .eq('name', name)
                .maybe_single()
                .execute()
            )
        except Exception as exc:
            if _is_missing_relation(exc):
                return False
            raise
        if not row.data:
            raise ValueError(f"Unknown client: {name}")
        return bool(row.data.get('is_launch_site'))

    def set_client_is_launch_site(self, name: str, value: bool) -> None:
        """Mark a client as a launch site (or not)."""
        self._require_client_exists(name)
        try:
            self._sb.table('clients').update({
                'is_launch_site': bool(value),
            }).eq('name', name).execute()
        except Exception as exc:
            if _is_missing_relation(exc):
                logger.error(
                    "clients.is_launch_site column missing for %r — %s",
                    name, _MIGRATION_HINT_COUNTERS,
                )
                raise ValueError(
                    "Cannot save launch-site flag: the clients.is_launch_site "
                    "column is missing. " + _MIGRATION_HINT_COUNTERS
                ) from exc
            raise

    def get_client_working_days(self, name: str) -> Optional[List[str]]:
        """Return the restricted set of working weekdays for a client, or None.

        Degrades to ``None`` (all weekdays) when the ``clients.working_days``
        column is missing (pre-migration database) or unset."""
        try:
            row = (
                self._sb.table('clients')
                .select('working_days')
                .eq('name', name)
                .maybe_single()
                .execute()
            )
        except Exception as exc:
            if _is_missing_relation(exc):
                return None
            raise
        if not row.data:
            raise ValueError(f"Unknown client: {name}")
        raw = row.data.get('working_days')
        if not raw:
            return None
        return [str(d).strip().lower() for d in raw]

    def set_client_working_days(
        self, name: str, value: Optional[List[str]],
    ) -> None:
        """Update a client's working-days restriction (None / [] = all days)."""
        self._require_client_exists(name)
        normalized = None
        if value:
            normalized = [str(d).strip().lower() for d in value if str(d).strip()]
            if not normalized:
                normalized = None
        try:
            self._sb.table('clients').update({
                'working_days': normalized,
            }).eq('name', name).execute()
        except Exception as exc:
            if _is_missing_relation(exc):
                logger.error(
                    "clients.working_days column missing for %r — %s",
                    name, _MIGRATION_HINT_COUNTERS,
                )
                raise ValueError(
                    "Cannot save working days: the clients.working_days "
                    "column is missing. " + _MIGRATION_HINT_COUNTERS
                ) from exc
            raise

    def get_client_item_cooldown_days(self, name: str) -> Optional[int]:
        """Return the client's item-cooldown override in days, or ``None`` when
        unset (use ``DEFAULT_ITEM_COOLDOWN_DAYS``) / pre-migration."""
        try:
            row = (
                self._sb.table('clients')
                .select('item_cooldown_days')
                .eq('name', name)
                .maybe_single()
                .execute()
            )
        except Exception as exc:
            if _is_missing_relation(exc):
                return None
            raise
        if not row.data:
            raise ValueError(f"Unknown client: {name}")
        return normalize_item_cooldown_days(row.data.get('item_cooldown_days'))

    def set_client_item_cooldown_days(self, name: str, value) -> None:
        """Update a client's item-cooldown window (days); None clears it."""
        self._require_client_exists(name)
        try:
            self._sb.table('clients').update({
                'item_cooldown_days': normalize_item_cooldown_days(value),
            }).eq('name', name).execute()
        except Exception as exc:
            if _is_missing_relation(exc):
                logger.error(
                    "clients.item_cooldown_days column missing for %r — %s",
                    name, _MIGRATION_HINT_COUNTERS,
                )
                raise ValueError(
                    "Cannot save cooldown setting: the "
                    "clients.item_cooldown_days column is missing. "
                    + _MIGRATION_HINT_COUNTERS
                ) from exc
            raise

    # ---- mutation methods --------------------------------------------------

    @staticmethod
    def _validate_counters(counters: List[Dict]) -> None:
        """Raise ValueError unless every counter has >=1 category."""
        if not counters:
            raise ValueError("At least one counter is required.")
        if len(counters) > MAX_COUNTERS:
            raise ValueError(f"At most {MAX_COUNTERS} counters are allowed.")
        for i, c in enumerate(counters):
            cats = c.get('categories') or []
            if not cats:
                raise ValueError(
                    f"Counter {i + 1} ('{c.get('name', '')}') needs at least "
                    "one food category."
                )
            # Mutually exclusive slot groups (e.g. plain curd vs curd/raita —
            # both are the yogurt side, a counter serves only one).
            cats_set = set(cats)
            for group in MUTUALLY_EXCLUSIVE_SLOT_GROUPS:
                clash = group & cats_set
                if len(clash) > 1:
                    labels = ' and '.join(
                        DISPLAY_SLOT_NAME.get(s, s) for s in sorted(clash)
                    )
                    raise ValueError(
                        f"Counter {i + 1} ('{c.get('name', '')}') selects "
                        f"{labels}, but these are mutually exclusive — pick "
                        "only one."
                    )

    def _counters_from_inputs(
        self,
        active_slots: List[str] | None,
        counter_mode: str,
        counters: List[Dict] | None,
    ) -> List[Dict]:
        """Normalise create/update inputs into the canonical counters list."""
        if counters:
            norm = [normalize_counter(c, i) for i, c in enumerate(counters)]
        else:
            cats = active_slots if active_slots is not None else list(_TOGGLEABLE_BASE_SLOTS)
            norm = [normalize_counter({'name': 'Counter 1', 'categories': cats}, 0)]
        if counter_mode != 'multi':
            norm = norm[:1]
        self._validate_counters(norm)
        return norm

    def create_client(
        self,
        name: str,
        active_slots: List[str] | None = None,
        *,
        counter_mode: str = 'single',
        counters: List[Dict] | None = None,
        city: str | None = None,
        serve_weekends: bool = False,
        item_cooldown_days=None,
        working_days=None,
        source_pools=None,
        is_launch_site: bool = False,
        shared_categories=None,
    ) -> None:
        """Create a new client. Config is stored entirely in ``counters``.

        Two ways to call:
          * classic single-counter: ``create_client(name, active_slots)``
          * counter-aware: ``create_client(name, counter_mode='multi',
            counters=[...])``

        ``city`` is an optional client location from ``AVAILABLE_CITIES``;
        ``serve_weekends`` flags a kitchen that also runs Sat/Sun;
        ``item_cooldown_days`` overrides the default cooldown window (None =
        default); ``working_days`` restricts the plan horizon to those weekdays
        (None = every weekday); ``source_pools`` are the extra ontology item
        pools this client draws from (``common`` is implicit).

        Every optional column is part of the same INSERT. They used to be
        applied by follow-up setters after the row existed, so a rejected value
        left a created-but-misconfigured client behind.
        """
        norm = self._counters_from_inputs(active_slots, counter_mode, counters)
        row = {
            'name': name, 'counters': norm,
            'city': normalize_city(city), 'serve_weekends': bool(serve_weekends),
            'item_cooldown_days': normalize_item_cooldown_days(item_cooldown_days),
        }
        # Only send the newer optional columns when the caller set them, so a
        # database that predates them still takes the common create path.
        if working_days is not None:
            row['working_days'] = self._normalize_working_days_value(working_days)
        if source_pools is not None:
            row['source_pools'] = sorted({
                t for t in (_normalize_pool_name(p) for p in source_pools)
                if t and t != COMMON_POOL
            })
        if is_launch_site:
            # Only send it when true, so a pre-migration DB still takes the
            # common create path (the column defaults to false there anyway).
            row['is_launch_site'] = True
        if shared_categories is not None:
            row['shared_categories'] = self._normalize_shared_categories_value(
                shared_categories)
        try:
            self._sb.table('clients').insert(row).execute()
        except Exception as exc:
            # Degrade gracefully on a database that predates the optional
            # clients.city / clients.serve_weekends columns: create the client
            # without them rather than hard-failing.
            if _is_missing_relation(exc):
                logger.error(
                    "optional clients column missing on create for %r — %s",
                    name, _MIGRATION_HINT_COUNTERS,
                )
                for optional in ('city', 'serve_weekends', 'item_cooldown_days',
                                 'working_days', 'source_pools', 'is_launch_site',
                                 'shared_categories'):
                    row.pop(optional, None)
                self._sb.table('clients').insert(row).execute()
            else:
                raise

    def set_client_city(self, name: str, city: str | None) -> None:
        """Update a client's city (normalised to ``AVAILABLE_CITIES`` / None)."""
        self._require_client_exists(name)
        try:
            self._sb.table('clients').update({
                'city': normalize_city(city),
            }).eq('name', name).execute()
        except Exception as exc:
            if _is_missing_relation(exc):
                logger.error(
                    "clients.city column missing for %r — %s",
                    name, _MIGRATION_HINT_COUNTERS,
                )
                raise ValueError(
                    "Cannot save city: the clients.city column is missing. "
                    + _MIGRATION_HINT_COUNTERS
                ) from exc
            raise

    def set_client_source_pools(self, name: str, pools) -> None:
        """Persist a client's extra item pools (F5). Tokens are normalized and
        deduped; ``common`` is implicit and never stored."""
        self._require_client_exists(name)
        norm = sorted({
            t for t in (_normalize_pool_name(p) for p in (pools or []))
            if t and t != COMMON_POOL
        })
        try:
            self._sb.table('clients').update({
                'source_pools': norm,
            }).eq('name', name).execute()
        except Exception as exc:
            if _is_missing_relation(exc):
                logger.error(
                    "clients.source_pools column missing for %r — %s",
                    name, _MIGRATION_HINT_COUNTERS,
                )
                raise ValueError(
                    "Cannot save source pools: the clients.source_pools column "
                    "is missing. " + _MIGRATION_HINT_COUNTERS
                ) from exc
            raise

    def set_client_shared_categories(self, name: str, categories) -> None:
        """Persist the base slots synced across this client's counters.

        Values are lower-cased, de-duped, and filtered to known base/const
        slots; unknown tokens are dropped.
        """
        self._require_client_exists(name)
        norm = self._normalize_shared_categories_value(categories)
        try:
            self._sb.table('clients').update({
                'shared_categories': norm,
            }).eq('name', name).execute()
        except Exception as exc:
            if _is_missing_relation(exc):
                logger.error(
                    "clients.shared_categories column missing for %r — %s",
                    name, _MIGRATION_HINT_COUNTERS,
                )
                raise ValueError(
                    "Cannot save shared categories: the "
                    "clients.shared_categories column is missing. "
                    + _MIGRATION_HINT_COUNTERS
                ) from exc
            raise

    def set_counters_for_client(
        self, name: str, counter_mode: str, counters: List[Dict],
    ) -> None:
        """Persist the full counter configuration for an existing client.

        ``clients.counters`` is the single store — no mirror tables. Writes the
        normalised list (one counter for single, the whole list for multi).
        """
        self._require_client_exists(name)
        norm = self._counters_from_inputs(None, counter_mode, counters)
        self._write_counters_column(name, norm)

    def update_primary_counter(
        self,
        name: str,
        *,
        active_base_slots: List[str] | None = None,
        slot_counts: Dict[str, int] | None = None,
        theme_map: Dict[str, str] | None = None,
    ) -> None:
        """Apply legacy per-field edits to the primary counter (counters[0]).

        Backward-compat for API clients that PUT ``active_base_slots`` /
        ``slot_counts`` / ``theme_map`` instead of a full ``counters`` list.
        Only the provided fields change; the rest of the config is preserved.
        """
        counters = self._counters_list(name)
        primary = dict(counters[0])
        if active_base_slots is not None:
            primary['categories'] = active_base_slots
        if slot_counts is not None:
            primary['slot_counts'] = slot_counts
        if theme_map is not None:
            primary['theme_map'] = theme_map
        counters[0] = normalize_counter(primary, 0)
        self._validate_counters(counters)
        self._write_counters_column(name, counters)

    def _write_counters_column(self, name: str, counters: List[Dict]) -> None:
        """Write the ``clients.counters`` JSONB column.

        Raises a clear error if the column is missing (the migration must be
        applied before multi-counter config can be saved).
        """
        try:
            self._sb.table('clients').update({
                'counters': counters,
            }).eq('name', name).execute()
        except Exception as exc:
            if _is_missing_relation(exc):
                logger.error(
                    "clients.counters column missing for %r — %s",
                    name, _MIGRATION_HINT_COUNTERS,
                )
                raise ValueError(
                    "Cannot save counter configuration: the clients.counters "
                    "column is missing. " + _MIGRATION_HINT_COUNTERS
                ) from exc
            raise

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
        # ON DELETE CASCADE on menu_history / week_signatures cleans up history.
        self._sb.table('clients').delete().eq('name', name).execute()

    # ---- optimistic concurrency -------------------------------------------

    def get_client_version(self, name: str) -> int:
        """Return the current version counter for a client.

        Fresh rows default to 1; every successful PUT bumps this by one. If the
        ``version`` column doesn't exist (unmigrated database), log and return
        1 — the editor stays usable, optimistic-concurrency just no-ops.
        """
        try:
            row = (
                self._sb.table('clients')
                .select('version')
                .eq('name', name)
                .maybe_single()
                .execute()
            )
        except Exception as exc:
            if _is_undefined_column(exc):
                logger.error(
                    "clients.version column missing — falling back to "
                    "version=1 for %r. %s",
                    name, _MIGRATION_HINT,
                )
                self._require_client_exists(name)
                return 1
            raise
        if not row.data:
            raise ValueError(f"Unknown client: {name}")
        return int(row.data.get('version', 1))

    def _require_client_exists(self, name: str) -> None:
        """Raise ValueError if no client row exists with this name."""
        row = (
            self._sb.table('clients')
            .select('name')
            .eq('name', name)
            .maybe_single()
            .execute()
        )
        if not row.data:
            raise ValueError(f"Unknown client: {name}")

    # --- value normalisation, shared by the per-field getters and the
    # --- combined get_client_row() so both return identical shapes.

    def _normalize_counters_value(self, name: str, raw) -> List[Dict]:
        """Normalise a raw ``counters`` column value (see _counters_list)."""
        if raw:
            return [normalize_counter(c, i) for i, c in enumerate(raw)]
        legacy = self._legacy_primary_counter(name)
        return [legacy] if legacy else [default_counter(0)]

    @staticmethod
    def _normalize_working_days_value(raw) -> Optional[List[str]]:
        if not raw:
            return None
        return [str(d).strip().lower() for d in raw]

    @staticmethod
    def _normalize_source_pools_value(raw) -> Optional[List[str]]:
        # None means "column unset" -> caller treats it as common-only ([]),
        # matching get_client_source_pools.
        if raw is None:
            return []
        return [_normalize_pool_name(t) for t in raw if _normalize_pool_name(t)]

    @staticmethod
    def _normalize_shared_categories_value(raw) -> List[str]:
        # None (column unset) -> []. Keep only known base/const slots, lower-
        # cased and de-duped, order preserved.
        if not raw:
            return []
        valid = set(BASE_SLOTS) | set(CONST_SLOTS)
        seen: Set[str] = set()
        out: List[str] = []
        for c in raw:
            s = str(c).strip().lower()
            if s in valid and s not in seen:
                seen.add(s)
                out.append(s)
        return out

    # Config columns that live directly on the ``clients`` row. Read together so
    # one request costs one round trip instead of one per field.
    _CONFIG_COLUMNS = (
        'counters', 'city', 'serve_weekends', 'working_days',
        'item_cooldown_days', 'source_pools', 'is_launch_site',
        'shared_categories', 'version',
    )

    def get_client_row(self, name: str) -> Dict[str, Any]:
        """Return every config column for *name* in a single query.

        The per-field getters each issued their own
        ``select('<one column>').eq('name', …)``, so a single ``GET
        /client-config`` cost seven round trips against the same row and
        ``POST /plan`` cost six. Reads stay live — this is still an
        uncached query per call — they are just no longer fragmented.

        Degrades on a pre-migration database: if the combined select fails
        because a column is missing, each field falls back to its own getter,
        which already handles the missing-column case individually.

        Raises:
            ValueError: when the client does not exist.
        """
        try:
            row = (
                self._sb.table('clients')
                .select(', '.join(self._CONFIG_COLUMNS))
                .eq('name', name)
                .maybe_single()
                .execute()
            )
        except Exception as exc:
            if _is_missing_relation(exc):
                return {
                    'counters': self._counters_list(name),
                    'city': self.get_client_city(name),
                    'serve_weekends': self.get_client_serve_weekends(name),
                    'working_days': self.get_client_working_days(name),
                    'item_cooldown_days': self.get_client_item_cooldown_days(name),
                    'source_pools': self.get_client_source_pools(name),
                    'is_launch_site': self.get_client_is_launch_site(name),
                    'shared_categories': self.get_client_shared_categories(name),
                    'version': self.get_client_version(name),
                }
            raise
        if not row.data:
            raise ValueError(f"Unknown client: {name}")
        data = dict(row.data)
        return {
            'counters': self._normalize_counters_value(name, data.get('counters')),
            'city': normalize_city(data.get('city')),
            'serve_weekends': bool(data.get('serve_weekends')),
            'working_days': self._normalize_working_days_value(
                data.get('working_days')),
            'item_cooldown_days': normalize_item_cooldown_days(
                data.get('item_cooldown_days')),
            'source_pools': self._normalize_source_pools_value(
                data.get('source_pools')),
            'is_launch_site': bool(data.get('is_launch_site')),
            'shared_categories': self._normalize_shared_categories_value(
                data.get('shared_categories')),
            'version': int(data.get('version') or 1),
        }

    def get_client_configs_from_row(self, name: str, row: Dict[str, Any]):
        """``[(counter_name, ClientConfig), …]`` built from an already-read row.

        Lets a caller that fetched the row once avoid re-reading it per counter.
        """
        out = []
        for counter in row['counters']:
            cfg = self._config_from_counter(name, counter)
            cfg.serve_weekends = row['serve_weekends']
            cfg.working_days = row['working_days']
            out.append((counter['name'], cfg))
        return out

    def normalize_counters_for_write(
        self, counter_mode: str, counters: List[Dict],
    ) -> List[Dict]:
        """Validate + normalise a counters payload without writing it.

        Split out of :meth:`set_counters_for_client` so a caller can validate
        every field of an update before any of it is persisted.
        """
        return self._counters_from_inputs(None, counter_mode, counters)

    def primary_counter_patch(
        self,
        name: str,
        *,
        active_base_slots: List[str] | None = None,
        slot_counts: Dict[str, int] | None = None,
        theme_map: Dict[str, str] | None = None,
    ) -> List[Dict]:
        """Return the full counters list with legacy per-field edits applied.

        The write-free half of :meth:`update_primary_counter`, so the legacy
        API shape can also go through the single atomic update.
        """
        counters = self._counters_list(name)
        primary = dict(counters[0])
        if active_base_slots is not None:
            primary['categories'] = active_base_slots
        if slot_counts is not None:
            primary['slot_counts'] = slot_counts
        if theme_map is not None:
            primary['theme_map'] = theme_map
        out = [normalize_counter(primary, 0)] + [
            normalize_counter(c, i) for i, c in enumerate(counters[1:], start=1)
        ]
        self._validate_counters(out)
        return out

    def update_client_atomic(
        self, name: str, expected: int, fields: Dict[str, Any],
    ) -> int:
        """Apply *fields* and bump ``version`` in ONE conditional UPDATE.

        ``fields`` holds already-validated, already-normalised column values
        (``counters``, ``city``, ``serve_weekends``, ``working_days``,
        ``item_cooldown_days``, ``source_pools``). Every one is a plain column on
        ``clients``, so they all fit in a single statement together with the
        version bump.

        This replaces a bump-then-N-setters sequence that was neither atomic nor
        safe: each setter was its own round trip, so any failure part-way left
        the row half-updated with ``version`` already incremented — and because
        input validation happened *between* those writes, a single malformed
        ``source_pools`` deterministically committed the earlier fields and then
        returned 400. One statement removes the partial-write window entirely
        and collapses the round trips.

        The ``version = expected`` predicate is still the race gate, so a stale
        writer changes nothing at all rather than clobbering a concurrent edit.

        Raises:
            ConcurrentEditError: when the update matches no rows.
        """
        new_version = int(expected) + 1
        payload = {**fields, 'version': new_version}
        try:
            result = (
                self._sb.table('clients')
                .update(payload)
                .eq('name', name)
                .eq('version', int(expected))
                .execute()
            )
        except Exception as exc:
            if _is_undefined_column(exc):
                # Pre-migration database: fall back to the per-field setters,
                # which each degrade individually with a migration hint.
                logger.error(
                    "clients.version (or a config column) missing — applying "
                    "%r without the concurrency check. %s", name, _MIGRATION_HINT,
                )
                self._require_client_exists(name)
                self._apply_fields_individually(name, fields)
                return 1
            raise
        if not result.data:
            current = self.get_client_version(name)  # raises ValueError if gone
            raise ConcurrentEditError(
                f"Client {name!r} has been modified by another request "
                f"(expected version {expected}, currently {current}). "
                "Refresh and retry.",
                current_version=current,
            )
        return new_version

    def _apply_fields_individually(self, name: str, fields: Dict[str, Any]) -> None:
        """Degraded path for a database missing the consolidated columns."""
        if 'counters' in fields:
            self._write_counters_column(name, fields['counters'])
        for column, setter in (
            ('city', self.set_client_city),
            ('serve_weekends', self.set_client_serve_weekends),
            ('working_days', self.set_client_working_days),
            ('item_cooldown_days', self.set_client_item_cooldown_days),
            ('source_pools', self.set_client_source_pools),
            ('is_launch_site', self.set_client_is_launch_site),
            ('shared_categories', self.set_client_shared_categories),
        ):
            if column in fields:
                try:
                    setter(name, fields[column])
                except ValueError as exc:
                    logger.warning(
                        "Could not apply %s for %r on the degraded path: %s",
                        column, name, exc,
                    )

    # NOTE: a standalone ``bump_version_if_matches`` used to live here. It was
    # the first half of the bump-then-write sequence that update_client_atomic
    # replaced, and after that refactor nothing called it. Keeping it would have
    # left the unsafe ordering available to the next caller who needed a version
    # bump, so it is gone; use update_client_atomic, which bumps the version in
    # the same statement as the fields it guards.

    # ---- validation --------------------------------------------------------

    def validate(self):
        """Validate configuration consistency. Raises ValueError on problems."""
        base_set = set(BASE_SLOTS)
        rows = self._sb.table('clients').select('name, counters').execute()
        for r in rows.data:
            counters = r.get('counters') or []
            if not isinstance(counters, list):
                raise ValueError(f"Client '{r['name']}' has a non-list counters value")
            for i, c in enumerate(counters):
                for cat in (c.get('categories') or []):
                    if cat not in base_set:
                        raise ValueError(
                            f"Client '{r['name']}' counter {i} has unknown "
                            f"category: {cat}"
                        )
                for day, theme in (c.get('theme_map') or {}).items():
                    if day.lower() not in DEFAULT_THEME_MAP:
                        raise ValueError(
                            f"Client '{r['name']}' counter {i} has invalid day: {day}"
                        )
                    if theme not in AVAILABLE_THEMES:
                        raise ValueError(
                            f"Client '{r['name']}' counter {i} has invalid theme: {theme}"
                        )
