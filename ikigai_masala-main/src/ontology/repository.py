"""Cached access to the per-city item ontologies.

This code lived in `api/app.py` as five module-level dicts and a lock. Two
problems with that, one of them measurable:

* **It is not an HTTP concern.** Loading a workbook, cleaning it, building slot
  pools and caching the result by resolved path has nothing to do with a request.
  Roughly 39% of `api/app.py` was this kind of thing, which is what made a
  2,200-line "API" module out of ~950 lines of actual API.

* **The caches were module globals, so tests reached in to reset them.** 18 test
  files repeated a five-line ritual — `for attr in ('_menu_data_by_path',
  '_nonveg_items_by_path', '_menu_rules_by_city', '_filtered_cache'):
  setattr(api_app, attr, {})` — 54 times in total. Miss one and the leak is
  silent: a stale 4,300-row Bangalore frame answers a Chennai test and the
  failure surfaces somewhere else entirely, depending on test order. That is now
  one call, `repository.reset()`.

One deliberate change of shape rather than pure relocation: the old
`_menu_data_for_client` read the client's row from Supabase itself to discover
`city` and `source_pools`. Reading a database row is not this layer's job, so
`filtered_menu_data` takes both explicitly and the caller (which already has the
row in hand, memoised on Flask's `g`) passes them down. The ontology layer no
longer touches the database at all, which is why it can be exercised without one.

Caches are keyed by RESOLVED PATH, never by city name: Chennai, Hyderabad and
NCR share Bangalore's workbook, and keying by city would hold four copies of a
4,300-row frame for nothing. The F5 pool cache is keyed by `(path, tokens)` for
the mirror-image reason — tokens alone would hand a Pune client Bangalore's
`common` pool.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class OntologyRepository:
    """Loads and caches item lists, slot pools, rulesets and derived name sets.

    One instance is shared per process (the module-level `repository`), but the
    class carries no global state, so a test wanting hard isolation can build its
    own rather than resetting the shared one.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        #: resolved workbook path -> (df, pools)
        self._menu_data_by_path: Dict[str, Tuple[Any, Any]] = {}
        #: (resolved path, frozenset(active pool tokens)) -> (df, pools)
        self._filtered_by_path_and_pools: Dict[Tuple[str, FrozenSet[str]],
                                               Tuple[Any, Any]] = {}
        #: resolved workbook path -> set of lowercased non-veg item names
        self._nonveg_by_path: Dict[str, Set[str]] = {}
        #: normalized city -> ruleset
        self._rules_by_city: Dict[Optional[str], List[Any]] = {}

    # -- loading -----------------------------------------------------------

    def menu_data(self, city=None) -> Tuple[Any, Any]:
        """Return ``(df, pools)`` for *city*'s ontology.

        A city without its own workbook falls back to the default (Bangalore)
        list, so `city=None` — every caller with no city in hand — behaves
        exactly as it always did.
        """
        from src.ontology.paths import city_excel_path, city_required_slots
        from src.preprocessor.data_cleanser import DataCleanser
        from src.preprocessor.excel_reader import ExcelReader
        from src.preprocessor.pool_builder import PoolBuilder

        path = city_excel_path(city)
        cached = self._menu_data_by_path.get(path)
        if cached is None:
            with self._lock:
                cached = self._menu_data_by_path.get(path)
                if cached is None:
                    df = DataCleanser(ExcelReader(path).read()).clean()
                    # A city ontology covers only the categories that city
                    # serves, so the mandatory-slot check is held to that city's
                    # declared set (data/raw/city_items/ontology_categories.json).
                    pools = PoolBuilder.build_pools(
                        df, required_slots=city_required_slots(city))
                    cached = (df, pools)
                    self._menu_data_by_path[path] = cached
                    logger.info("Loaded ontology for city=%r from %s (%d items)",
                                city, path, len(df))
        return cached

    def filtered_menu_data(self, city, source_pools) -> Tuple[Any, Any]:
        """``(df, pools)`` narrowed to a client's eligible item pools (F5).

        * ``source_pools is None`` (column missing / pre-migration) → the full
          ontology, i.e. unchanged behaviour until the migration is applied.
        * otherwise → only items eligible for ``common ∪ source_pools``, with the
          per-slot pools rebuilt from that subset.

        Two properties matter for a city whose list carries **no ``common``
        pool** (NCR — every row is tagged to a real client):

        * The required-slot check is NOT applied to a per-client subset. It is an
          *ontology-integrity* check ("a category the list should have and does
          not is a mapping regression"), and that belongs on the full city list
          (``menu_data`` still enforces it). A single client legitimately serves
          only some slots; a slot its pool cannot fill surfaces per-counter in
          ``diagnose``/the solve, not as a build-time 500. For a city that DOES
          have ``common`` (Bangalore/Chennai/Pune) this changes nothing —
          ``common`` already covers every declared slot, so the subset does too.
        * If the eligible subset is **empty** — a client that configured no
          ``source_pools`` in a city with no ``common`` — fall back to the full
          city list rather than planning from nothing. "No pools configured"
          then means "not narrowed", the same as ``None``.

        Takes `source_pools` as an argument rather than reading the client row:
        see the module docstring.
        """
        from src.ontology.paths import city_excel_path
        from src.preprocessor.client_pool_filter import (
            filter_eligible, get_active_pools)
        from src.preprocessor.pool_builder import PoolBuilder

        df, pools = self.menu_data(city)
        if source_pools is None:
            return df, pools
        active = get_active_pools(source_pools)
        key = (city_excel_path(city), frozenset(active))
        cached = self._filtered_by_path_and_pools.get(key)
        if cached is None:
            with self._lock:
                cached = self._filtered_by_path_and_pools.get(key)
                if cached is None:
                    fdf = filter_eligible(df, active)
                    if fdf is None or len(fdf) == 0:
                        cached = (df, pools)          # no eligible items → full
                    else:
                        cached = (fdf, PoolBuilder.build_pools(
                            fdf, required_slots=set()))
                    self._filtered_by_path_and_pools[key] = cached
        return cached

    # -- derived views -----------------------------------------------------

    def nonveg_items(self, city=None) -> Set[str]:
        """Lowercased non-veg item base-names for *city*.

        An item is non-veg when its ``primary_protein`` is a non-veg protein OR
        its ``is_egg_dish`` flag is set — the latter catches egg dishes the data
        mislabels with a veg protein (`anda_mirch_masala` tagged `chana`). Used
        to tag solver output so non-veg dishes render red in the app and the
        Excel download.
        """
        from src.ontology.paths import city_excel_path
        from src.preprocessor.pool_builder import _nonveg_mask

        path = city_excel_path(city)
        cached = self._nonveg_by_path.get(path)
        if cached is None:
            df, _ = self.menu_data(city)
            if 'item' not in getattr(df, 'columns', []):
                cached = set()
            else:
                # The same predicate the pool builder uses to drop non-veg items
                # from veg slots — one source of truth for "is this dish non-veg".
                cached = {str(n).strip().lower()
                          for n in df.loc[_nonveg_mask(df), 'item']}
            self._nonveg_by_path[path] = cached
        return cached

    def item_names(self, city=None) -> FrozenSet[str]:
        """Lowercased item names, for resolving a client constant pin to a dish.

        City-scoped: a pin is resolved against the list the client's city really
        serves, so a dish existing only in another city's ontology stays a
        stamped constant instead of becoming a solver candidate with no pool row.
        """
        df = self.menu_data(city)[0]
        if df is None or 'item' not in getattr(df, 'columns', []):
            return frozenset()
        try:
            return frozenset(str(v).strip().lower() for v in df['item'].tolist())
        except Exception:  # noqa: BLE001 — never break planning over a pin lookup
            return frozenset()

    def rules_for_city(self, city) -> List[Any]:
        """Cached base ruleset for a city — resolves `city_rules/<city>.json` and
        its ``extends`` chain, falling back to the default city. Cached per
        normalized city so clients in one city share a read-only ruleset."""
        from src.menu_rules.menu_rule_loader import MenuRuleLoader

        key = (city or '').strip().lower() or None
        cached = self._rules_by_city.get(key)
        if cached is None:
            with self._lock:
                cached = self._rules_by_city.get(key)
                if cached is None:
                    cached = MenuRuleLoader().load_for_city(city)
                    self._rules_by_city[key] = cached
        return cached

    # -- lifecycle ---------------------------------------------------------

    def reset(self) -> None:
        """Drop every cache. Replaces the five-line setattr ritual that 18 test
        files used to repeat; also the hook for picking up an edited workbook or
        ruleset without a restart."""
        with self._lock:
            self._menu_data_by_path.clear()
            self._filtered_by_path_and_pools.clear()
            self._nonveg_by_path.clear()
            self._rules_by_city.clear()

    def cache_sizes(self) -> Dict[str, int]:
        """Entry counts per cache — for the metrics endpoint and for tests that
        assert cities sharing a workbook share one entry."""
        return {
            'menu_data': len(self._menu_data_by_path),
            'filtered': len(self._filtered_by_path_and_pools),
            'nonveg': len(self._nonveg_by_path),
            'rules': len(self._rules_by_city),
        }


#: Process-wide instance. `api/app.py` and the Streamlit editor share it so one
#: workbook load serves every request, exactly as the module globals did.
repository = OntologyRepository()
