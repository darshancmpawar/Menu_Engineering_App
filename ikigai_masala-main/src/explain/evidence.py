"""Build the EvidencePack — the only thing the explanation layer may assert.

Pure. No network, no LLM, no Flask, no Streamlit. Takes plain data in and
returns a JSON-serialisable dict, so every case here is testable without a
solver or a database.

The pack answers two separate questions and keeps them separate:

  1. "Does the plate work together?"  -> `plate_profile` + `checks` (checks.py)
  2. "Why THIS dish?"                 -> `provenance`

Everything in `provenance` is recovered from state the solver already computes
and currently discards. `recency_by_item` in particular is threaded all the way
into `MenuSolver` for the freshness objective and then dropped on the floor;
surfacing it costs nothing and is the single most convincing line in the output
("not served for 26 days" is a fact a chef can check).

`relaxations` is the honesty channel — see `attach_relaxations`.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence
import datetime as dt
import logging

from .checks import Check, base_slot, plate_profile, run_checks

logger = logging.getLogger(__name__)

# Ontology columns the pack carries per dish. Anything not listed is not
# available to the renderer or the model, by design — a narrow surface is what
# makes the validator downstream able to police the output.
DISH_COLUMNS = (
    'course_type', 'cuisine_family', 'item_color', 'texture', 'spice_level',
    'richness_score', 'key_ingredient', 'primary_protein', 'sub_category',
)

# A dish is worth calling out as "fresh" only past this gap. Below it the claim
# is true but boring, and boring claims crowd out the useful ones.
FRESHNESS_DAYS_THRESHOLD = 14


def _clean(value: Any) -> Any:
    """Coerce a pandas/numpy scalar to something `json.dumps` accepts.

    Pandas hands back `numpy.int64` and `numpy.float64`, neither of which is
    JSON-serialisable. A pack that cannot be serialised cannot be cached or
    sent to a model, so this runs on every value on the way in rather than
    being discovered at the API boundary.
    """
    if value is None:
        return None
    for attr in ('item',):                      # numpy scalar -> python scalar
        if hasattr(value, attr):
            try:
                value = getattr(value, attr)()
                break
            except Exception:                   # pragma: no cover
                pass
    if isinstance(value, (str, int, float, bool)):
        s = str(value).strip()
        if s.lower() in ('', 'nan', 'none', 'nat'):
            return None
        return value
    s = str(value).strip()
    return None if s.lower() in ('', 'nan', 'none', 'nat') else s


def _norm(name: Any) -> str:
    return str(name or '').strip().lower().replace(' ', '_')


def build_dishes(day_items: Dict[str, Any],
                 attrs: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """`{slot: item_base}` + ontology lookup -> `{slot: {name, ...columns}}`.

    `day_items` values may be a bare item string or the `/plan` response's
    `{'item_base': ..., 'is_nonveg': ...}` dict; both are accepted so callers do
    not have to reshape the solution first.

    A dish missing from `attrs` still appears in the pack with `name` only. It
    must not be dropped: a dish the renderer cannot describe is exactly the one
    worth showing a human, and silently omitting it would make the plate look
    better than it is.
    """
    out: Dict[str, Dict[str, Any]] = {}
    for slot, raw in (day_items or {}).items():
        if isinstance(raw, dict):
            name = raw.get('item_base') or raw.get('item')
        else:
            name = raw
        if not name:
            continue
        row = attrs.get(str(name).strip()) or attrs.get(_norm(name)) or {}
        entry: Dict[str, Any] = {'name': str(name).strip(),
                                 'slot': slot,
                                 'base_slot': base_slot(slot)}
        for col in DISH_COLUMNS:
            entry[col] = _clean(row.get(col))
        if not row:
            logger.debug("explain: no ontology row for %r (slot %s)", name, slot)
        out[slot] = entry
    return out


def build_provenance(dishes: Dict[str, Dict[str, Any]],
                     recency: Optional[Dict[str, int]] = None,
                     theme: Optional[str] = None,
                     constant_items: Optional[Dict[str, Any]] = None,
                     rule_notes: Optional[Dict[str, str]] = None) -> List[Dict[str, str]]:
    """Why each dish is on the plate. First matching reason wins, per dish.

    Order matters and is deliberate: a pinned dish is on the plate because the
    client pinned it, regardless of how long it has been since it last ran. The
    strongest true reason is the one worth printing.
    """
    recency = {_norm(k): v for k, v in (recency or {}).items()}
    pinned = {_norm(v if not isinstance(v, dict) else v.get('item'))
              for v in (constant_items or {}).values()}
    rule_notes = rule_notes or {}
    out: List[Dict[str, str]] = []

    for slot, d in dishes.items():
        name = d['name']
        key = _norm(name)

        if key in pinned:
            out.append({'dish': name, 'slot': slot, 'reason': 'client_constant',
                        'detail': 'pinned for this counter every serving day'})
            continue

        note = rule_notes.get(slot) or rule_notes.get(base_slot(slot))
        if note:
            out.append({'dish': name, 'slot': slot, 'reason': 'rule',
                        'detail': str(note)})
            continue

        days = recency.get(key)
        if days is not None and days >= FRESHNESS_DAYS_THRESHOLD:
            out.append({'dish': name, 'slot': slot, 'reason': 'freshness',
                        'detail': f'not served for {int(days)} days'})
            continue

        cuisine = d.get('cuisine_family')
        if theme and cuisine and _norm(cuisine).startswith(_norm(theme)[:5]):
            out.append({'dish': name, 'slot': slot, 'reason': 'theme',
                        'detail': f'matches the {theme} theme for this day'})
            continue

    return out


def build_evidence(*,
                   date: Any,
                   day_items: Dict[str, Any],
                   attrs: Dict[str, Dict[str, Any]],
                   theme: Optional[str] = None,
                   client_name: Optional[str] = None,
                   counter_name: Optional[str] = None,
                   city: Optional[str] = None,
                   recency: Optional[Dict[str, int]] = None,
                   constant_items: Optional[Dict[str, Any]] = None,
                   rule_notes: Optional[Dict[str, str]] = None,
                   relaxations: Optional[Sequence[Dict[str, str]]] = None,
                   ) -> Dict[str, Any]:
    """Assemble one day's pack. This dict is the model's entire world."""
    dishes = build_dishes(day_items, attrs)
    checks: List[Check] = run_checks(dishes)

    if isinstance(date, (dt.date, dt.datetime)):
        date_str = date.strftime('%Y-%m-%d')
        weekday = date.strftime('%A')
    else:
        date_str = str(date)
        weekday = ''
        try:
            weekday = dt.date.fromisoformat(date_str).strftime('%A')
        except ValueError:
            pass

    return {
        'date': date_str,
        'weekday': weekday,
        'theme': theme,
        'client': client_name,
        'counter': counter_name,
        'city': city,
        'dishes': dishes,
        'plate_profile': plate_profile(dishes),
        'checks': [c.to_dict() for c in checks],
        'provenance': build_provenance(dishes, recency, theme,
                                       constant_items, rule_notes),
        'relaxations': [dict(r) for r in (relaxations or [])],
    }


def build_plan_evidence(*,
                        solution: Dict[str, Any],
                        attrs: Dict[str, Dict[str, Any]],
                        **common: Any) -> List[Dict[str, Any]]:
    """One pack per served day, in date order.

    Non-working days are skipped: a blank column has no plate to describe, and
    `_span_dates` deliberately keeps them in the solution so the table does not
    close the gap up.
    """
    packs: List[Dict[str, Any]] = []
    for date_key in sorted(solution or {}):
        entry = solution[date_key] or {}
        if entry.get('is_working_day') is False:
            continue
        items = entry.get('items') or {}
        if not items:
            continue
        packs.append(build_evidence(
            date=date_key,
            day_items=items,
            attrs=attrs,
            theme=entry.get('day_type'),
            **common,
        ))
    return packs


def attrs_from_dataframe(df: Any) -> Dict[str, Dict[str, Any]]:
    """Cleansed ontology DataFrame -> `{item: {column: value}}`.

    Kept here rather than in the caller so the lookup shape is defined once.
    Both the exact name and a normalised key are registered, because the
    solution carries `item_base` while history and configs sometimes carry a
    normalised form.
    """
    out: Dict[str, Dict[str, Any]] = {}
    cols = [c for c in DISH_COLUMNS if c in getattr(df, 'columns', [])]
    for record in df[['item'] + cols].to_dict('records'):
        name = str(record.get('item') or '').strip()
        if not name:
            continue
        row = {c: record.get(c) for c in cols}
        out[name] = row
        out.setdefault(_norm(name), row)
    return out


def attach_relaxations(packs: Iterable[Dict[str, Any]],
                       records: Sequence[Dict[str, str]]) -> None:
    """Fold captured solver warnings into every pack, in place.

    The solver already logs when it quietly gives up — `selector_frequency`
    emits "min 2 capped to 1 - the rule is under-enforced", `daily_min` emits
    "floor relaxed for that day". Those go to a log nobody reads.

    Surfacing them is what turns this feature from marketing copy into a
    diagnostic: a chef reading "why this menu" should be told which rule did not
    hold, not handed a summary that papers over it.

    Relaxations are plan-wide rather than per-day because the solver does not
    always know which day a capped `min` cost it.
    """
    shared = [dict(r) for r in records]
    for p in packs:
        p['relaxations'] = shared
