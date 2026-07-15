"""
Client configuration loader — Supabase backend.

Every read queries Supabase directly so any change made via the UI,
API, or dashboard is immediately reflected on the next call.

Schema:
    menu_categories (name TEXT PK, slots TEXT[])
    clients         (name TEXT PK, menu_category TEXT FK → menu_categories.name,
                     version INT NOT NULL DEFAULT 1)
    slot_count_overrides (client_name, slot, count)
    theme_overrides      (client_name, day, theme)
    app_settings         (key, value)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Set

from src.constants import (
    BASE_SLOT_NAMES as BASE_SLOTS,
    CONST_SLOTS,
)
from src.db import get_supabase
from src.preprocessor.pool_builder import _expand_slots_in_order

logger = logging.getLogger(__name__)


# Postgres error code for "undefined_column"; raised by the Supabase REST
# layer when a SELECT / UPDATE references a column that doesn't exist —
# e.g. when a deployment hasn't applied the Phase 2 #14 migration that
# added clients.version. Detecting it lets us degrade gracefully (the
# editor keeps working) while logging a loud, actionable hint so the
# operator knows to run scripts/create_tables.sql.
_PG_UNDEFINED_COLUMN = "42703"
# Postgres "undefined_table" plus the PostgREST schema-cache codes it maps
# to (PGRST205 = table missing from the cache, PGRST204 = column missing).
_PG_UNDEFINED_TABLE = "42P01"
_MIGRATION_HINT = (
    "Re-run scripts/create_tables.sql in the Supabase SQL editor to apply "
    "the latest migrations. Optimistic-concurrency on PUT /client-config "
    "is degraded until the column exists."
)
_MIGRATION_HINT_COUNTERS = (
    "Re-run scripts/create_tables.sql in the Supabase SQL editor to create "
    "the client_counters table and the clients.counter_mode / counter_count "
    "columns. Multi-counter configs fall back to the legacy single-counter "
    "storage until the migration is applied."
)


def _is_undefined_column(exc: BaseException) -> bool:
    """Return True if *exc* looks like a Postgres undefined-column error.

    Supabase-py wraps PostgREST errors in a class with ``code`` and
    ``message`` attributes, but the exact class name has shifted across
    versions, so check both the structured field and the stringified
    message as a fallback.
    """
    if getattr(exc, "code", None) == _PG_UNDEFINED_COLUMN:
        return True
    msg = str(exc).lower()
    return "does not exist" in msg and "column" in msg


def _is_missing_relation(exc: BaseException) -> bool:
    """Return True if *exc* looks like a missing table / column / schema-cache
    error — i.e. the multi-counter migration hasn't been applied yet.

    Covers the raw Postgres codes (undefined_column / undefined_table) and
    the PostgREST wrappers (``PGRST205`` unknown table, ``PGRST204`` unknown
    column), plus a stringified-message fallback for supabase-py versions
    that don't surface ``code``.
    """
    code = getattr(exc, "code", None)
    if code in (_PG_UNDEFINED_COLUMN, _PG_UNDEFINED_TABLE, "PGRST205", "PGRST204"):
        return True
    msg = str(exc).lower()
    return (
        "does not exist" in msg
        or "could not find" in msg
        or "schema cache" in msg
    )

DEFAULT_THEME_MAP: Dict[str, str] = {
    'monday': 'mix',
    'tuesday': 'chinese',
    'wednesday': 'biryani',
    'thursday': 'south',
    'friday': 'north',
}

AVAILABLE_THEMES: List[str] = ['mix', 'chinese', 'biryani', 'south', 'north']


class ConcurrentEditError(ValueError):
    """Raised when an optimistic-concurrency version check fails.

    The ``current_version`` attribute carries the version that's actually
    in the database right now so callers can surface it (e.g. in a 409
    response body) and the client can refresh + retry.
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
# serves, how many of each (frequency), and the per-weekday theme. A client is
# either 'single' (one counter — the classic setup) or 'multi' (N counters).
# The canonical in-memory shape is:
#     {'name': str, 'categories': [slot],
#      'slot_counts': {slot: int}, 'theme_map': {day: theme}}

# Frequency bounds mirror the editor's number_input (1..3 per category).
_MIN_SLOT_COUNT = 1
_MAX_SLOT_COUNT = 3
# Hard cap on counters per client — keeps the editor UI and payloads sane.
MAX_COUNTERS = 6

_TOGGLEABLE_BASE_SLOTS: List[str] = [s for s in BASE_SLOTS if s not in CONST_SLOTS]


def default_counter(index: int = 0, name: str = "") -> Dict:
    """Return a fresh counter config with sensible defaults.

    Defaults to every (non-constant) category active at frequency 1 and the
    global default day themes — the same starting point the single-counter
    editor used before multi-counter existed.
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
    - clamps every ``slot_counts`` value to [1, 3]; only keeps active categories
    - merges ``theme_map`` over the global defaults, ignoring invalid days/themes
    - falls back to ``Counter N`` for a blank name
    """
    raw = raw or {}
    name = str(raw.get('name') or '').strip() or f'Counter {index + 1}'

    cats = _dedupe_preserve_order([
        c for c in (raw.get('categories') or [])
        if c in BASE_SLOTS and c not in CONST_SLOTS
    ])

    raw_counts = raw.get('slot_counts') or {}
    slot_counts: Dict[str, int] = {}
    for c in cats:
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
    """
    Loads client configuration from Supabase.

    Every property and method issues a live query — there is no in-memory
    cache, so data is always consistent with the database.
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
                expanded.extend(
                    _expand_slots_in_order([slot], {slot: slot_counts.get(slot, 1)})
                )
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
        """Return slots for a menu_category. Raises ValueError when missing/empty."""
        if not cat_name:
            raise ValueError(
                "Client has no menu category assigned. "
                "Please assign a menu category with slots to this client, "
                "or delete the client."
            )
        row = (
            self._sb.table('menu_categories')
            .select('slots')
            .eq('name', cat_name)
            .maybe_single()
            .execute()
        )
        if not row.data or not row.data.get('slots'):
            raise ValueError(
                f"Menu category '{cat_name}' has no slots configured. "
                f"Please configure slots for this category in the "
                f"customisation editor, or delete the client."
            )
        return row.data['slots']

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

    # ---- counter read methods ----------------------------------------------

    def get_counter_mode(self, name: str) -> str:
        """Return 'single' or 'multi' for a client.

        Falls back to 'single' when the ``counter_mode`` column is missing
        (pre-migration deployment) — the editor stays usable and the client
        behaves as a classic single-counter client.
        """
        try:
            row = (
                self._sb.table('clients')
                .select('counter_mode')
                .eq('name', name)
                .maybe_single()
                .execute()
            )
        except Exception as exc:
            if _is_missing_relation(exc):
                logger.error(
                    "clients.counter_mode missing for %r — %s",
                    name, _MIGRATION_HINT_COUNTERS,
                )
                self._require_client_exists(name)
                return 'single'
            raise
        if not row.data:
            raise ValueError(f"Unknown client: {name}")
        return 'multi' if row.data.get('counter_mode') == 'multi' else 'single'

    def get_counters_for_client(self, name: str) -> List[Dict]:
        """Return the ordered list of counter configs for a client.

        Reads the ``client_counters`` table. When no rows exist (a legacy
        single-counter client, or the table hasn't been migrated in yet) a
        single counter is synthesised from the legacy menu_category /
        slot_count_overrides / theme_overrides so callers always get at
        least one usable counter.
        """
        rows = None
        try:
            resp = (
                self._sb.table('client_counters')
                .select('*')
                .eq('client_name', name)
                .order('counter_index')
                .execute()
            )
            rows = resp.data
        except Exception as exc:
            if not _is_missing_relation(exc):
                raise
            logger.error(
                "client_counters unavailable for %r — %s",
                name, _MIGRATION_HINT_COUNTERS,
            )

        counters: List[Dict] = []
        for r in sorted(rows or [], key=lambda x: x.get('counter_index', 0)):
            counters.append(normalize_counter({
                'name': r.get('counter_name'),
                'categories': r.get('categories'),
                'slot_counts': r.get('slot_counts'),
                'theme_map': r.get('theme_map'),
            }, r.get('counter_index', 0)))

        if counters:
            return counters
        return [self._legacy_single_counter(name)]

    def _legacy_single_counter(self, name: str) -> Dict:
        """Synthesise one counter from the classic single-counter tables."""
        try:
            base = self.get_active_slots_for_client(name)
        except ValueError:
            # Client has no / an empty menu category — fall back to the
            # default category set rather than blowing up the editor.
            base = list(_TOGGLEABLE_BASE_SLOTS)
        cats = [s for s in base if s not in CONST_SLOTS]
        counts = self.get_slot_counts_for_client(name)
        theme = self.get_theme_map_for_client(name)
        return normalize_counter({
            'name': 'Counter 1',
            'categories': cats,
            'slot_counts': {c: counts.get(c, 1) for c in cats},
            'theme_map': theme,
        }, 0)

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

    def create_client(
        self,
        name: str,
        active_slots: List[str] | None = None,
        *,
        counter_mode: str = 'single',
        counters: List[Dict] | None = None,
    ) -> None:
        """Create a new client. Auto-assigns or creates a menu_category.

        Two ways to call:
          * classic single-counter: ``create_client(name, active_slots)`` —
            unchanged behaviour, one implicit counter.
          * counter-aware: ``create_client(name, counter_mode='multi',
            counters=[...])`` — persists each counter and mirrors the
            primary one into the legacy tables.
        """
        if counters:
            norm = [normalize_counter(c, i) for i, c in enumerate(counters)]
            self._validate_counters(norm)
            primary_cats = norm[0]['categories']
            cat_name = self.find_or_create_menu_category(primary_cats)
            self._sb.table('clients').insert({
                'name': name,
                'menu_category': cat_name,
            }).execute()
            self.set_counters_for_client(name, counter_mode, norm)
            return

        if active_slots is None:
            active_slots = list(_TOGGLEABLE_BASE_SLOTS)
        cat_name = self.find_or_create_menu_category(active_slots)
        self._sb.table('clients').insert({
            'name': name,
            'menu_category': cat_name,
        }).execute()

    @staticmethod
    def _validate_counters(counters: List[Dict]) -> None:
        """Raise ValueError unless every counter has ≥1 category."""
        if not counters:
            raise ValueError("At least one counter is required.")
        if len(counters) > MAX_COUNTERS:
            raise ValueError(f"At most {MAX_COUNTERS} counters are allowed.")
        for i, c in enumerate(counters):
            if not c.get('categories'):
                raise ValueError(
                    f"Counter {i + 1} ('{c.get('name', '')}') needs at least "
                    "one food category."
                )

    def set_counters_for_client(
        self, name: str, counter_mode: str, counters: List[Dict],
    ) -> None:
        """Persist the full counter configuration for an existing client.

        - normalises + validates every counter
        - mirrors the primary counter (index 0) into the legacy
          menu_category / slot_count_overrides / theme_overrides tables so
          the solver keeps working unchanged
        - replaces the ``client_counters`` rows and updates the client's
          ``counter_mode`` / ``counter_count`` (both degrade gracefully if
          the migration hasn't been applied)
        """
        self._require_client_exists(name)
        normalized = [normalize_counter(c, i) for i, c in enumerate(counters)]
        mode = 'multi' if counter_mode == 'multi' else 'single'
        if mode == 'single':
            normalized = normalized[:1]
        self._validate_counters(normalized)

        primary = normalized[0]
        self.update_client_slots(name, primary['categories'])
        self.update_client_slot_counts(name, primary['slot_counts'])
        self.update_client_theme_overrides(name, primary['theme_map'])

        self._write_counter_rows(name, normalized)
        self._set_counter_meta(name, mode, len(normalized))

    def _write_counter_rows(self, name: str, counters: List[Dict]) -> None:
        """Replace all ``client_counters`` rows for a client.

        Degrades to a no-op (with a loud log) if the table hasn't been
        migrated in — the legacy mirror written by the caller still keeps
        single-counter planning working.
        """
        try:
            self._sb.table('client_counters').delete().eq(
                'client_name', name,
            ).execute()
            rows = [
                {
                    'client_name': name,
                    'counter_index': i,
                    'counter_name': c['name'],
                    'categories': c['categories'],
                    'slot_counts': c['slot_counts'],
                    'theme_map': c['theme_map'],
                }
                for i, c in enumerate(counters)
            ]
            if rows:
                self._sb.table('client_counters').insert(rows).execute()
        except Exception as exc:
            if _is_missing_relation(exc):
                logger.error(
                    "Could not persist client_counters for %r — %s",
                    name, _MIGRATION_HINT_COUNTERS,
                )
                return
            raise

    def _set_counter_meta(self, name: str, mode: str, count: int) -> None:
        """Update clients.counter_mode / counter_count (best-effort)."""
        try:
            self._sb.table('clients').update({
                'counter_mode': mode,
                'counter_count': int(count),
            }).eq('name', name).execute()
        except Exception as exc:
            if _is_missing_relation(exc):
                logger.error(
                    "clients.counter_mode/counter_count missing for %r — %s",
                    name, _MIGRATION_HINT_COUNTERS,
                )
                return
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
        # CASCADE on FK deletes slot_count_overrides & theme_overrides
        self._sb.table('clients').delete().eq('name', name).execute()

    # ---- optimistic concurrency -------------------------------------------

    def get_client_version(self, name: str) -> int:
        """Return the current version counter for a client.

        Fresh rows and rows created post-migration default to 1; every
        successful PUT through the API bumps this by one. If the
        ``version`` column doesn't exist (deployment hasn't applied the
        Phase 2 #14 migration), log a clear ERROR and return 1 — the
        editor stays usable, optimistic-concurrency just no-ops until
        the migration runs.
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
                # Confirm the row exists at all so callers still get the
                # right ValueError for a typo'd client name.
                self._require_client_exists(name)
                return 1
            raise
        if not row.data:
            raise ValueError(f"Unknown client: {name}")
        return int(row.data.get('version', 1))

    def _require_client_exists(self, name: str) -> None:
        """Raise ValueError if no client row exists with this name.

        Used by version-related fallbacks so the loader still 404s on
        a typo even when the version column itself isn't queryable.
        """
        row = (
            self._sb.table('clients')
            .select('name')
            .eq('name', name)
            .maybe_single()
            .execute()
        )
        if not row.data:
            raise ValueError(f"Unknown client: {name}")

    def bump_version_if_matches(self, name: str, expected: int) -> int:
        """Atomically bump ``version`` from *expected* to *expected+1*.

        Implemented as a conditional update — the WHERE clause includes
        ``version = expected``, so concurrent writers race at the DB and
        only one succeeds. Zero rows affected means our version is stale
        (someone else wrote between our GET and PUT) or the client was
        deleted.

        If the ``version`` column doesn't exist (pre-migration
        deployment), the conditional filter blows up — we log an ERROR
        and fall back to a non-conditional UPDATE so writes still go
        through (without the optimistic-concurrency check). The hint in
        the log tells operators what to do.

        Raises:
            ConcurrentEditError: when the update matches no rows. The
                error carries the *current* version so callers can feed
                it back to the user.
        """
        new_version = int(expected) + 1
        try:
            result = (
                self._sb.table('clients')
                .update({'version': new_version})
                .eq('name', name)
                .eq('version', int(expected))
                .execute()
            )
        except Exception as exc:
            if _is_undefined_column(exc):
                logger.error(
                    "clients.version column missing — bumping without "
                    "concurrency check for %r. %s",
                    name, _MIGRATION_HINT,
                )
                self._require_client_exists(name)
                # No concurrency guard available; just touch the row to
                # confirm it exists and return 1 so the response surface
                # stays consistent.
                return 1
            raise
        if not result.data:
            # Distinguish "client missing" from "version stale" so the
            # 409 response body can include the live value.
            current = self.get_client_version(name)  # raises ValueError if gone
            raise ConcurrentEditError(
                f"Client {name!r} has been modified by another request "
                f"(expected version {expected}, currently {current}). "
                "Refresh and retry.",
                current_version=current,
            )
        return new_version

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
