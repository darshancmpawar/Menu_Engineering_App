"""Turning "Thursday is a Tamil Nadu day" into rules the solver already has.

Two inputs reach this module and it flattens them into one ``{date: Region}``
map for the horizon:

* ``region_map`` — ``{weekday: region}`` on the counter, the client's standing
  weekly pattern.
* ``region_days`` — ``{iso_date: region}`` on the request, what the planner
  sends when somebody picks a region for one day of the plan on screen. It WINS,
  because it is the more specific statement and the more recent one.

Weekdays are resolved to dates *here*, where the horizon is visible, rather than
in the rule: a plan can start mid-week and span two ISO weeks, so "Thursday"
inside one horizon may mean two different days or none.

No new rule type. A regional day is a ``selector_frequency`` floor plus a
``soft_preference`` top-up, both scoped with ``only_on_dates`` — the floor puts
three regional dishes on the plate and the preference fills the remaining cells
with regional dishes wherever no real rule objects. That split is the whole
design: the hard part is small enough to always be satisfiable, and the part
that makes the day actually READ regional can be outbid by every constraint
that matters.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..constants import WEEKDAY_NAMES, canonical_weekday
from ..menu_rules.selector_frequency_rule import _iso_day as _iso
from ..ontology.regions import MIN_REGION_SLOTS, Region, region_by_name


def normalize_region_map(value: Any, regions: Sequence[Region]) -> Dict[str, str]:
    """A stored `region_map` -> `{weekday: canonical region name}`.

    Drops a weekday nobody recognises and a region this city cannot theme, so a
    map written against another city (or against a workbook that has since lost
    a region) cannot smuggle a dead name into a rule. Rejecting at the write is
    the point — note 9's silent config mismatch is expensive precisely because
    the plan still comes back and looks fine.
    """
    if not isinstance(value, Mapping):
        return {}
    out: Dict[str, str] = {}
    for raw_day, raw_region in value.items():
        full = canonical_weekday(raw_day)
        if not full:
            continue
        region = region_by_name(regions, str(raw_region))
        if region is None or not region.is_themeable:
            continue
        out[full] = region.name
    return out


def resolve_region_days(
    dates: Sequence[Any],
    day_themes: Sequence[str],
    regions: Sequence[Region],
    *,
    region_map: Optional[Mapping[str, str]] = None,
    region_days: Optional[Mapping[str, str]] = None,
) -> Tuple[Dict[str, Region], List[Dict[str, Any]]]:
    """Flatten both inputs to `{iso date: Region}`, plus what could not be used.

    The second return value is a list of problem dicts, each carrying enough to
    say WHY on screen — an unknown region, one too thin for this city, or one
    whose cuisine the day's theme excludes. They are reported rather than
    silently dropped: a Tamil Nadu pick on a Chinese Thursday is not a menu the
    solver can make, and finding that out from a plate with no Tamil food on it
    is the worst way to learn it.
    """
    chosen: Dict[str, Region] = {}
    problems: List[Dict[str, Any]] = []
    by_iso = {_iso(d): i for i, d in enumerate(dates)}

    # Weekday pattern first, then the per-date picks over the top of it.
    wanted: Dict[str, str] = {}
    if region_map:
        by_day = {canonical_weekday(k): v for k, v in region_map.items()}
        for d in dates:
            name = by_day.get(WEEKDAY_NAMES[d.weekday()])
            if name:
                wanted[_iso(d)] = str(name)
    for raw_date, name in (region_days or {}).items():
        iso = _iso(raw_date)
        if not str(name or '').strip():
            wanted.pop(iso, None)      # an explicit "no region" clears the map
            continue
        wanted[iso] = str(name)

    for iso, name in sorted(wanted.items()):
        if iso not in by_iso:
            continue                   # outside this horizon; not an error
        region = region_by_name(regions, name)
        if region is None:
            problems.append({
                'date': iso, 'region': name, 'reason': 'unknown',
                'message': f"{name!r} is not a region in this city's item list.",
            })
            continue
        if not region.is_themeable:
            problems.append({
                'date': iso, 'region': region.name, 'reason': 'too_thin',
                'message': (
                    f"{region.name} clears the weekly floor on only "
                    f"{len(region.deep_slots)} slot(s) here; a regional day "
                    f"needs {MIN_REGION_SLOTS}."),
            })
            continue
        theme = (str(day_themes[by_iso[iso]]).lower()
                 if by_iso[iso] < len(day_themes) else '')
        if not region.compatible_with(theme):
            problems.append({
                'date': iso, 'region': region.name, 'reason': 'theme_conflict',
                'theme': theme,
                'message': (
                    f"{region.name} is {'/'.join(sorted(region.cuisine_families)) or 'regional'} "
                    f"and this day is themed {theme}. The theme filter removes "
                    f"every {region.name} dish from the main slots before the "
                    f"regional floor is read, so the day cannot carry it."),
            })
            continue
        chosen[iso] = region
    return chosen, problems


def region_rule_configs(
    chosen: Mapping[str, Region],
    served_base_slots: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    """Rule configs for a resolved `{date: Region}` map.

    One PAIR of rules per region rather than per date, so a week with two Tamil
    days costs two rules and not four. `only_on_dates` carries the grouping.

    A region whose usable slots do not survive this counter's served set yields
    nothing at all — no rule is better than a floor of zero, which would read as
    applied in every diagnostic while constraining nothing.
    """
    by_region: Dict[str, Tuple[Region, List[str]]] = {}
    for iso, region in sorted(chosen.items()):
        entry = by_region.setdefault(region.name, (region, []))
        entry[1].append(iso)

    out: List[Dict[str, Any]] = []
    for name, (region, isos) in sorted(by_region.items()):
        slots = list(region.usable_slots(served_base_slots))
        floor = region.floor_for(served_base_slots)
        if not slots or floor <= 0:
            continue
        slug = _slug(name)
        selector = {'state_origin': region.name}
        out.append({
            'name': f'region_{slug}_floor',
            'type': 'selector_frequency',
            'enabled': True,
            'selector': selector,
            'base_slot': slots,
            'daily_min': floor,
            'only_on_dates': list(isos),
            '_comment': (
                f"Regional day: at least {floor} {name} dish(es) across "
                f"{', '.join(slots)}. Relaxes per day to what the pool can "
                f"place, so it can never make a plan impossible."),
        })
        out.append({
            'name': f'region_{slug}_prefer',
            'type': 'soft_preference',
            'enabled': True,
            # `prefer_cells`, not `prefer_daily`. The daily mode scores a DAY:
            # once the floor above has put one regional dish on the plate its
            # penalty is already zero, so pairing the two bought nothing at all
            # — measured, a floor of 3 over 5 slots came back with exactly 3.
            # This scores each CELL, which is what carries the day past the
            # floor and makes it read regional rather than merely contain three
            # regional dishes.
            'mode': 'prefer_cells',
            'selector': selector,
            'base_slot': slots,
            # LOW, deliberately. Above the freshness objective in a cell but
            # below every real rule, so a regional day never costs a colour, a
            # protein, a premium cap or a client's own frequency — it only
            # decides cells nothing else had an opinion about. It is also the
            # tier that keeps note 32's already-inverted theme rung from
            # widening: ~6 slots x 25 days at 1e6 is 0.15 of one MEDIUM unit.
            'priority': 'low',
            'only_on_dates': list(isos),
            '_comment': (
                f"Regional day: prefer {name} dishes in the remaining "
                f"{', '.join(slots)} cells, where no rule objects."),
        })
    return out


def _slug(name: str) -> str:
    keep = [c.lower() if c.isalnum() else '_' for c in str(name)]
    slug = ''.join(keep).strip('_')
    while '__' in slug:
        slug = slug.replace('__', '_')
    return slug or 'region'
