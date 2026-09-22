"""Which regions a city's item list can actually theme a day with.

The ontology's `state_origin` column names the Indian state a dish comes from.
It is 100% filled and only about a quarter informative: three rows in four sit
in a pan-level bucket (`Pan-North India`, `Pan-South India`, `Europe (foreign)`)
whose `region_reason` reads "no sub-regional signal" — those are not regional
facts, they are the absence of one spelled as a value. `admin_type` is what
separates the two, and it is the only one of the six regional columns that
means the same thing in every city: `state_confidence` is `high` on nine
Bangalore rows and zero Pune ones, and `region_authority` has no `UNRESOLVED`
bucket at all in Pune or Hyderabad while Bangalore is 66% of it. So the gate
here is `admin_type`, never confidence or authority.

**A region is a floor, never a filter.** Bangalore holds 47 Punjabi veg gravies
and *zero* Punjabi rice and *zero* Punjabi bread. Narrowing those slots the way
`ThemeSlotFilterRule` narrows a cuisine would empty them — which is
`scripts/ncr_south_bread.py`'s incident exactly, where three south breads became
none under the cooldown and the solve went INFEASIBLE with no starved slot to
point at. So this module's job is to say, per region, *which slots can carry it*
— and the rule built from that asks for N dishes across those slots and nothing
of the others.

Everything degrades to "no regions" when the column is absent, which is the
state of every committed workbook today.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, Mapping, Optional, Sequence, Tuple

from ..preprocessor.column_mapper import _norm_cell

#: The column naming the state, and the one saying whether that name IS a state.
REGION_COL = 'state_origin'
ADMIN_COL = 'admin_type'

#: `admin_type` values that carry a real region. The other two — `non_state`
#: and `foreign` — are the pan-level buckets above.
STATE_ADMIN_TYPES = frozenset({'state', 'union_territory'})

#: Distinct regional dishes a slot needs before it can carry a WEEKLY regional
#: day. A weekly day comes round about three times inside the 20-day item
#: cooldown, plus the week being planned, so four is the floor — the same
#: arithmetic note 25 gives for sizing any count-1 slot.
SLOT_DISH_FLOOR = 4

#: Slots a region must clear before it is worth offering at all. Below this the
#: day would carry one or two regional dishes and read as an ordinary menu, so
#: the picker greys the region out rather than letting it quietly disappoint.
MIN_REGION_SLOTS = 4

#: How many dishes a regional day asks for. Deliberately small: the point is a
#: day that READS regional, not one that fights the colour, protein and
#: key-ingredient variety rules for every cell.
DEFAULT_REGION_FLOOR = 3

#: Which `cuisine_family` values each day theme admits in its cuisine-main
#: slots, mirroring `ThemeSlotFilterRule`. `None` means the theme narrows
#: nothing, so any region is fine; an EMPTY set means the theme narrows by flag
#: rather than by cuisine (chinese / continental / biryani), and a region has no
#: way in — its dishes are removed before any floor could be read.
THEME_CUISINES: Mapping[str, Optional[FrozenSet[str]]] = {
    'mix': None,
    'south': frozenset({'south_indian'}),
    'north': frozenset({'north_indian'}),
    'chinese': frozenset(),
    'continental': frozenset(),
    'biryani': frozenset(),
    # The meta-theme resolves per ISO-week parity to chinese or continental,
    # and NEITHER takes a region. Listing it matters: an unknown theme reads as
    # "narrows nothing" below, so leaving it out would have offered every
    # region on a day whose main slots are flag-narrowed to Chinese food.
    'chinese_continental': frozenset(),
}


@dataclass(frozen=True)
class Region:
    """One state, and what a day themed on it could actually be made of."""

    name: str
    #: The `cuisine_family` values its dishes carry. In practice one: every
    #: southern state is 100% `south_indian` and every northern one 100%
    #: `north_indian` (drinks aside, which no theme filters). That is what makes
    #: the theme/region compatibility matrix DERIVED rather than hand-written,
    #: so it cannot drift as the workbooks change.
    cuisine_families: FrozenSet[str]
    #: base slot -> distinct regional dishes available in it
    slot_counts: Mapping[str, int]

    @property
    def deep_slots(self) -> Tuple[str, ...]:
        """Slots that can carry this region every week."""
        return tuple(sorted(
            s for s, n in self.slot_counts.items() if n >= SLOT_DISH_FLOOR))

    @property
    def total_dishes(self) -> int:
        return sum(self.slot_counts.values())

    @property
    def is_themeable(self) -> bool:
        return len(self.deep_slots) >= MIN_REGION_SLOTS

    def floor_for(self, served_slots: Optional[Sequence[str]] = None) -> int:
        """How many regional dishes to ask for, given the slots a counter runs.

        Capped to the deep slots the counter actually serves, so a counter with
        two of the region's slots is asked for two rather than three. The rule
        would cap itself anyway (`daily_min` relaxes to what a day can place),
        but relaxing is a thing worth reporting and this is not — it is just
        arithmetic nobody needs to read about.
        """
        usable = self.usable_slots(served_slots)
        return max(0, min(DEFAULT_REGION_FLOOR, len(usable)))

    def usable_slots(self, served_slots: Optional[Sequence[str]] = None
                     ) -> Tuple[str, ...]:
        """The deep slots this counter serves — the floor's `base_slot` list.

        Derived from the region's own depth rather than a fixed set. That is
        what keeps the floor satisfiable: Punjab's runs over gravy, veg dry,
        dal, non-veg and dessert, and rice and bread are simply not part of it.
        A relaxation then means one thing only — the pool ran out THIS WEEK
        under the cooldown — instead of also meaning "this city never had a
        Punjabi rice", which is a fact about the item list and belongs in the
        picker, where it is visible before anyone generates anything.
        """
        deep = self.deep_slots
        if served_slots is None:
            return deep
        served = {str(s) for s in served_slots}
        return tuple(s for s in deep if s in served)

    def compatible_with(self, day_theme: str) -> bool:
        admitted = THEME_CUISINES.get(str(day_theme or '').lower(), None)
        if admitted is None:                  # theme narrows nothing
            return True
        if not admitted:                      # narrows by flag — no way in
            return False
        return bool(self.cuisine_families & admitted)

    def as_dict(self) -> Dict[str, Any]:
        """JSON shape for `/editor-metadata` and the planner."""
        return {
            'name': self.name,
            'cuisine_families': sorted(self.cuisine_families),
            'deep_slots': list(self.deep_slots),
            'slot_counts': {k: int(v) for k, v in sorted(self.slot_counts.items())},
            'themeable': self.is_themeable,
            'themes': sorted(t for t in THEME_CUISINES if self.compatible_with(t)),
        }


def has_region_data(df) -> bool:
    """True when this workbook carries the regional columns at all.

    Every committed workbook answers False today — the columns arrived with the
    client's corrected city lists, which are not installed. Callers treat that
    as "no regional days available" rather than an error, so nothing about the
    product changes until the data lands.
    """
    try:
        cols = set(df.columns)
    except AttributeError:                    # pragma: no cover - not a frame
        return False
    return REGION_COL in cols and ADMIN_COL in cols


def measure_regions(df) -> Tuple[Region, ...]:
    """Every single-state region in *df*, with its per-slot depth.

    Returns regions that are too thin to theme as well as ones that are not:
    the picker greys those out *with their counts*, so an operator can see a
    region was weighed and rejected rather than forgotten. Sorted by depth, so
    the useful ones come first.
    """
    if not has_region_data(df):
        return ()
    if 'course_type' not in df.columns or 'item' not in df.columns:
        return ()                              # pragma: no cover - malformed

    admin = df[ADMIN_COL].map(_norm_cell)
    states = df[REGION_COL].map(_norm_cell)
    course = df['course_type'].map(_norm_cell)
    cuisine = (df['cuisine_family'].map(_norm_cell)
               if 'cuisine_family' in df.columns else None)
    names = df['item'].map(_norm_cell)

    keep = admin.isin(STATE_ADMIN_TYPES) & (states != '') & (names != '')
    if not bool(keep.any()):
        return ()

    out = []
    for raw in sorted(set(states[keep])):
        sel = keep & (states == raw)
        counts: Dict[str, int] = {}
        for slot in sorted(set(course[sel])):
            if not slot:
                continue
            n = int(names[sel & (course == slot)].nunique())
            if n:
                counts[slot] = n
        if not counts:
            continue                           # pragma: no cover - no dishes
        fams = frozenset(
            c for c in (set(cuisine[sel]) if cuisine is not None else set())
            if c and c != 'drink'
        )
        # `df[REGION_COL]` is normalised for matching but PRINTED to an
        # operator, so the workbook's own spelling is what the picker shows and
        # what a rule selector has to carry.
        original = str(df.loc[sel.index[sel], REGION_COL].iloc[0]).strip()
        out.append(Region(name=original or raw, cuisine_families=fams,
                          slot_counts=counts))
    out.sort(key=lambda r: (-len(r.deep_slots), -r.total_dishes, r.name))
    return tuple(out)


def themeable(regions: Sequence[Region]) -> Tuple[Region, ...]:
    return tuple(r for r in regions if r.is_themeable)


def region_by_name(regions: Sequence[Region], name: str) -> Optional[Region]:
    """Look a region up by name, tolerating case and stray spacing.

    Exact-match-only is the shape of the `clients.name` defect in note 9 — a
    near miss that loads as zero rules while `/plan` still answers 200 — so a
    name that differs only in case resolves rather than silently doing nothing.
    """
    want = _norm_cell(name)
    if not want:
        return None
    for r in regions:
        if _norm_cell(r.name) == want:
            return r
    return None
