"""
Pool builder: maps normalized DataFrame rows into per-slot item pools.

Each pool is a DataFrame containing only the items eligible for that slot.
Handles sambar/rasam splitting, welcome_drink mapping, and slot expansion.
"""

from typing import Dict, List, Optional, Set

import pandas as pd

from .column_mapper import _norm_str
from src.constants import (
    SLOT_SUFFIX_SEP, BASE_SLOT_NAMES, DEFAULT_OFF_SLOTS, COMBO_CATEGORIES,
    NONVEG_PROTEINS, NONVEG_SLOT,
)


def _nonveg_mask(frame: pd.DataFrame) -> pd.Series:
    """Boolean mask of non-vegetarian rows: ``primary_protein`` is a non-veg
    protein, or the ``is_egg_dish`` flag is set."""
    if 'primary_protein' in frame.columns:
        pp = frame['primary_protein'].map(_norm_str)
    else:
        pp = pd.Series('', index=frame.index)
    if 'is_egg_dish' in frame.columns:
        egg = pd.to_numeric(frame['is_egg_dish'], errors='coerce').fillna(0) == 1
    else:
        egg = pd.Series(False, index=frame.index)
    return pp.isin(NONVEG_PROTEINS) | egg

# course_type -> slot mapping for simple 1:1 cases
_SIMPLE_MAPPING: Dict[str, Set[str]] = {
    'welcome_drink': {'welcome_drink', 'infused_water'},
    'soup': {'soup'},
    'salad': {'salad'},
    'starter': {'starter'},
    'bread': {'bread'},
    'rice': {'rice'},
    'healthy_rice': {'healthy_rice', 'healthy rice', 'healthy-rice'},
    'dal': {'dal'},
    'veg_gravy': {'veg_gravy'},
    'veg_dry': {'veg_dry'},
    'nonveg_main': {'nonveg_main'},
    'curd_side': {'curd_side'},
    'dessert': {'dessert'},
}


# ---------------------------------------------------------------------------
# Slot helpers
# ---------------------------------------------------------------------------

def _base_slot(slot_id: str) -> str:
    s = _norm_str(slot_id)
    if SLOT_SUFFIX_SEP in s:
        left, right = s.rsplit(SLOT_SUFFIX_SEP, 1)
        if right.isdigit():
            return left
    return s


def _slot_num(slot_id: str) -> Optional[int]:
    s = _norm_str(slot_id)
    if SLOT_SUFFIX_SEP in s:
        _, right = s.rsplit(SLOT_SUFFIX_SEP, 1)
        if right.isdigit():
            return int(right)
    return None


def _expand_slots_in_order(base_slots: List[str], slot_counts: Dict[str, int]) -> List[str]:
    """Expand base slot names into numbered instances based on slot_counts."""
    out: List[str] = []
    for s in base_slots:
        n = int(slot_counts.get(s, 1))
        if n <= 0:
            continue
        if n == 1:
            out.append(s)
        else:
            out.extend(f'{s}{SLOT_SUFFIX_SEP}{i}' for i in range(1, n + 1))
    return out


# ---------------------------------------------------------------------------
# PoolBuilder
# ---------------------------------------------------------------------------

class PoolBuilder:
    """
    Builds per-slot item pools from a normalized DataFrame.

    Usage:
        pools = PoolBuilder.build_pools(df)
    """

    @staticmethod
    def build_pools(
        df: pd.DataFrame, required_slots: Optional[Set[str]] = None,
    ) -> Dict[str, pd.DataFrame]:
        """
        Build pools dict mapping each base slot name to the eligible items.

        Handles sambar/rasam splitting where course_type='sambar/rasam' is
        split by item name containing 'rasam'.

        *required_slots* are the base slots that MUST come out non-empty; an
        empty one raises, because a slot the ontology is expected to cover and
        does not is a column-mapping regression, not a menu decision. ``None``
        means "every mandatory base slot" — the right expectation for an
        ontology covering the whole product. A **city** ontology legitimately
        covers only the categories that city serves (Pune has no non-veg
        station and no sambar/rasam at all), so its caller passes the declared
        set from ``data/raw/city_items/ontology_categories.json``. Pass an
        empty set to skip the check entirely.
        """
        pools: Dict[str, pd.DataFrame] = {}

        # Simple 1:1 course_type -> slot mappings
        for slot, course_types in _SIMPLE_MAPPING.items():
            pools[slot] = df[df['course_type'].isin(course_types)].copy()

        # Special handling: sambar/rasam split
        is_rasam_text = df['item'].str.contains('rasam', na=False)
        pools['rasam'] = df[
            (df['course_type'] == 'rasam') |
            ((df['course_type'] == 'sambar/rasam') & is_rasam_text)
        ].copy()
        pools['sambar'] = df[
            (df['course_type'] == 'sambar') |
            ((df['course_type'] == 'sambar/rasam') & ~is_rasam_text)
        ].copy()

        # Plain-curd station: driven by the is_plain_curd flag (plain-curd
        # dishes live under the curd_side course_type but are a distinct,
        # curd-only category selectable per client).
        if 'is_plain_curd' in df.columns:
            pools['curd'] = df[
                pd.to_numeric(df['is_plain_curd'], errors='coerce').fillna(0) == 1
            ].copy()
        else:
            pools['curd'] = df.iloc[0:0].copy()

        # Curd-rice station: driven by the is_curd_rice flag rather than a
        # course_type (curd-rice dishes live under curd_side / rice courses).
        if 'is_curd_rice' in df.columns:
            pools['curd_rice'] = df[
                pd.to_numeric(df['is_curd_rice'], errors='coerce').fillna(0) == 1
            ].copy()
        else:
            pools['curd_rice'] = df.iloc[0:0].copy()

        # A curd rice belongs to the curd-rice station, not the flavoured-rice
        # slot. Because the station is flag-driven while the dish's course_type is
        # `rice`, every curd rice sat in BOTH pools — so a counter running `rice`
        # and `curd_rice` together could serve the SAME dish twice on one day, and
        # ToastTab CHN did exactly that (dry_fruits_curd_rice as Tuesday's
        # flavoured rice AND its curd rice). `unique_items` could not stop it: the
        # curd-rice staple declaration deliberately exempts the dish so it may
        # recur across days, and that exemption also permitted the same-day pair.
        #
        # Same reasoning as the non-veg exclusion just below — a dish appears in
        # the slot that IS its category, not in every slot whose column it happens
        # to satisfy. 13 dishes in Bangalore, 2 in Chennai; three live counters
        # (Computa Centre, ToastTab, ToastTab CHN) could hit it.
        if 'is_curd_rice' in df.columns and len(pools.get('rice', [])) > 0:
            is_cr = pd.to_numeric(
                pools['rice']['is_curd_rice'], errors='coerce').fillna(0) == 1
            pools['rice'] = pools['rice'][~is_cr].copy()

        # Combination categories: one slot whose pool is the union of two
        # component pools. The solver picks the per-day variant by course_type.
        for combo, (maj, minr) in COMBO_CATEGORIES.items():
            parts = [pools.get(maj), pools.get(minr)]
            parts = [p for p in parts if p is not None and len(p) > 0]
            if parts:
                pools[combo] = (
                    pd.concat(parts).drop_duplicates(subset='item').copy()
                )
            else:
                pools[combo] = df.iloc[0:0].copy()

        # Non-veg items may appear ONLY in the nonveg_main slot. Drop them from
        # every other slot so a veg slot (starter, rice, veg_gravy, …) can never
        # serve a non-veg dish, even if the ontology mis-files one (e.g. an egg
        # fried rice under course_type=rice).
        for slot, pool in pools.items():
            if slot == NONVEG_SLOT or len(pool) == 0:
                continue
            pools[slot] = pool[~_nonveg_mask(pool)].copy()

        # Validate the required base slots have items. Optional (default-off)
        # stations like curd_rice may legitimately be empty in a minimal
        # ontology — they only matter when a client explicitly selects them.
        if required_slots is None:
            required = [s for s in BASE_SLOT_NAMES if s not in DEFAULT_OFF_SLOTS]
        else:
            required = [s for s in BASE_SLOT_NAMES if s in required_slots]
        for slot in required:
            if slot not in pools or len(pools[slot]) == 0:
                raise ValueError(f"Slot '{slot}' has 0 items after mapping.")

        return pools
