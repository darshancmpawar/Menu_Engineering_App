"""Client-based item-pool filtering.

The ontology's ``client`` column tags each item with the client pool(s) it
belongs to — a comma-separated list, e.g. ``"Cloudera,Healthineers,Infineon"``.
An item may belong to several pools. The special pool ``common`` is shared by
every client and is always included.

A target (app) client stores a set of ``source_pools`` (database pool tokens)
in its config. The eligible item pool for that client is:

    eligible = items whose pool set intersects (source_pools ∪ {"common"})

Parsing is by exact, comma-split, case-insensitive token match — never
substring / ``str.contains``, so "Infineon" never accidentally matches
"Infineon Labs".

This module is pure (no Supabase, no solver) so it is trivially testable and
has zero blast radius on the existing pipeline until it is wired in.
"""

from __future__ import annotations

from typing import Iterable, Set

import pandas as pd

COMMON_POOL = "common"


def normalize_name(value) -> str:
    """Canonical form of a client-pool token: trimmed, case-folded.

    A pandas NaN (an empty ``client`` cell read from a workbook) is a float,
    and ``float('nan') or ''`` is truthy, so a naive ``str(value or '')`` would
    coin the spurious token ``'nan'``. Treat NaN / None as empty.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip().casefold()


def parse_client_pools(value) -> Set[str]:
    """Parse a raw ``client`` cell into a set of normalized pool tokens.

    Comma-separated, trimmed, case-folded, empties dropped. Exact-match only.
    A NaN / None cell (an untagged row) yields no tokens — never the string
    ``'nan'``.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return set()
    return {
        normalize_name(client)
        for client in str(value).split(",")
        if normalize_name(client)
    }


def get_active_pools(source_pools: Iterable[str]) -> Set[str]:
    """The active pool set for a client: its configured ``source_pools`` plus
    the always-included ``common`` pool."""
    active = {normalize_name(pool) for pool in (source_pools or [])}
    active.add(COMMON_POOL)
    return active


def item_is_eligible(item_pools: Set[str], active_pools: Set[str]) -> bool:
    """An item is eligible when at least one of its pool memberships matches an
    active pool."""
    return bool(item_pools & active_pools)


def add_client_pool_column(
    df: pd.DataFrame, client_col: str = "client", out_col: str = "client_pool_set",
) -> pd.DataFrame:
    """Parse the client memberships once into a set-valued column.

    Returns the same DataFrame (mutated in place and returned) with ``out_col``
    added. If ``client_col`` is absent, every item is treated as ``common`` so
    the ontology still works when the column is missing.
    """
    if client_col in df.columns:
        df[out_col] = df[client_col].apply(parse_client_pools)
    else:
        df[out_col] = [{COMMON_POOL} for _ in range(len(df))]
    return df


def filter_eligible(
    df: pd.DataFrame,
    active_pools: Set[str],
    *,
    client_col: str = "client",
    id_col: str = "item_id",
) -> pd.DataFrame:
    """Return the subset of ``df`` eligible for ``active_pools``, deduplicated
    by ``id_col`` (falling back to ``item`` if no id column).

    ``active_pools`` must already include ``common`` (call
    :func:`get_active_pools`). Pure: returns a copy, never mutates the input's
    row membership.
    """
    pool_sets = (
        df["client_pool_set"]
        if "client_pool_set" in df.columns
        else df[client_col].apply(parse_client_pools)
        if client_col in df.columns
        else pd.Series([{COMMON_POOL}] * len(df), index=df.index)
    )
    mask = pool_sets.apply(lambda item_pools: item_is_eligible(item_pools, active_pools))
    eligible = df[mask].copy()
    dedupe_col = id_col if id_col in eligible.columns else "item"
    if dedupe_col in eligible.columns:
        eligible = eligible.drop_duplicates(subset=[dedupe_col])
    return eligible


def available_pool_tokens(df: pd.DataFrame, client_col: str = "client") -> Set[str]:
    """Every distinct client-pool token present in the ontology (excluding
    ``common``, which is implicit). Used to populate the config UI and to
    validate that a client's configured ``source_pools`` are real tokens.
    """
    tokens: Set[str] = set()
    if client_col in df.columns:
        for cell in df[client_col]:
            tokens |= parse_client_pools(cell)
    tokens.discard(COMMON_POOL)
    return tokens
