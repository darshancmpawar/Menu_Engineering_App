"""Which dishes on the day's plate work WITH each other, and why.

`checks.py` scores the plate as a whole — four colours, three textures, average
richness 2.6. Those are properties of a set, and a chef reading them still has
to work out what they mean for the meal. This module answers the other half of
the question: *these two dishes, together, for this reason.*

    Chicken Chettinad (hot) with Boondi Raita — the yogurt cools it
    Paneer Butter Masala (rich 5) with Cucumber Salad (light 1) — cuts through
    Dal Tadka (saucy) with Wheat Chapati (bready) — something to carry it

Every claim is a statement about two attribute values the pack already carries,
so nothing here is an opinion the reader has to take on trust, and the whole
module stays inside the provenance boundary `api/explain_llm.py::validate`
polices — the numbers and dish names in a generated sentence about a pairing all
come from the pack.

**It abstains, and says so.** A plate with two rich gravies and nothing fresh
gets `summary` = "nothing on this plate offsets the rich dishes", not silence
and not a compliment. That is the same discipline as the relaxation channel
(note 31): a feature that only ever reports good news is not a diagnostic, and a
chef who catches it flattering one bad plate stops believing the good ones.

**The whole plate counts here, not `MAIN_COURSES`.** That is the opposite of
every check in `checks.py`, deliberately: a raita, a buttermilk and a papad are
excluded from *counting* the plate because a condiment's colour says nothing
about whether lunch works, but the raita is precisely what makes the biryani
work. Excluding it would throw away the most useful pairing on the plate.

No LLM, no I/O, no pandas — pure functions over the same plain dicts
`checks.py` reads, so a pairing can be pinned in a unit test.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable, Dict, List, Optional

from .checks import SPICE_NAMES, base_slot, main_dishes

# --- the vocabulary these rules read ---------------------------------------
# `texture` is 99.9% populated across the city lists and takes seven values:
# saucy, dry, grainy, crisp, fresh, soft, bready.
SAUCY = 'saucy'
CRISP = 'crisp'
FRESH = 'fresh'
DRY = 'dry'

# What a saucy dish is eaten WITH. Bread and rice, by their texture rather than
# their slot, because a counter can serve rice from `rice`, `white_rice`,
# `healthy_rice` or a biryani in `nonveg_main`.
CARRIER_TEXTURES = frozenset({'bready', 'grainy'})

# Textures that need relief rather than providing it.
SOFT_TEXTURES = frozenset({SAUCY, 'soft'})

# The cooling side. `is_raita` / `is_buttermilk` / `is_plain_curd` are not in
# `evidence.DISH_COLUMNS`, so this reads what IS there: yogurt as the dish's
# recorded protein, or one of the three yogurt stations by slot. Both, because
# a raita's protein is reliably `yogurt` while a plain curd's row sometimes
# leaves it blank and is identified by sitting in the curd slot.
COOLING_PROTEINS = frozenset({'yogurt'})
COOLING_SLOTS = frozenset({'curd', 'curd_side', 'curd_rice'})

# --- thresholds -------------------------------------------------------------
# `spice_level` is 0-3; 2 is "hot" and is where a cooling side stops being
# optional. `richness_score` is 0-5.
HOT_SPICE = 2
RICH_AT = 4
LIGHT_AT = 1
# Below this share of soft/saucy dishes a crisp item is pleasant but not
# relief, and calling it relief on a varied plate is the kind of overclaim that
# makes the rest of the output suspect.
SOFT_SHARE_FOR_RELIEF = 0.5


@dataclass(frozen=True)
class Pairing:
    """Two dishes and the reason they belong on a plate together.

    `detail` is the sentence a human reads and a model may paraphrase.
    `evidence` holds the two attribute values behind it, so the claim is
    checkable and the validator can source every number in the paraphrase.
    """
    kind: str
    detail: str
    dishes: List[str]
    slots: List[str]
    evidence: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _text(dish: Dict[str, Any], key: str) -> str:
    v = dish.get(key)
    if v is None:
        return ''
    s = str(v).strip().lower()
    return '' if s in ('nan', 'none') else s


def _num(dish: Dict[str, Any], key: str) -> Optional[float]:
    """The numeric value, or None for anything that is not one.

    One return for "no usable value" whether the cell is absent, None, a blank
    string or a `nan` marker — a second sentinel here is how an unscored dish
    ends up nominated as the plate's lightener.
    """
    v = dish.get(key)
    if v is None:
        return None
    if isinstance(v, str) and v.strip().lower() in ('', 'nan', 'none', 'nat'):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f          # NaN is never equal to itself


def _pretty(name: str) -> str:
    return str(name or '').replace('_', ' ').strip()


def _is_cooling(slot: str, dish: Dict[str, Any]) -> bool:
    return (base_slot(slot) in COOLING_SLOTS
            or _text(dish, 'primary_protein') in COOLING_PROTEINS)


def _by(dishes: Dict[str, Dict[str, Any]], key: str, want: float,
        highest: bool, exclude: Optional[set] = None) -> Optional[tuple]:
    """The (slot, dish, value) with the most/least *key*, or None.

    A dish with no recorded value is skipped rather than treated as zero — a
    blank `richness_score` read as 0 would nominate an unscored dish as the
    plate's lightener and the claim would be unfounded.

    *exclude* holds slots an earlier pairing already spoke about. Preferring a
    dish nobody has mentioned yet is what stops the output saying "curd cools
    it" and then "curd at 1 cuts through it" two lines later — both true, one
    sentence of information. It falls BACK to an excluded dish rather than
    abstaining, because the claim is still true and the caller's "every line
    must introduce a dish" guard is what decides whether it earns a line.
    """
    scored = []
    for slot, d in sorted(dishes.items()):
        v = _num(d, key)
        if v is None:
            continue
        if (v >= want) if highest else (v <= want):
            scored.append((v, slot, d))
    if not scored:
        return None
    fresh = [t for t in scored if t[1] not in (exclude or set())]
    pick = fresh or scored
    v, slot, d = (max(pick, key=lambda t: t[0]) if highest
                  else min(pick, key=lambda t: t[0]))
    return slot, d, v


def _pick(dishes: Dict[str, Dict[str, Any]], predicate,
          exclude: Optional[set] = None) -> List[tuple]:
    """Matching (slot, dish) pairs, unmentioned ones first, slot-sorted.

    Sorted so two runs over the same plate render the same sentence: `dishes`
    is keyed by slot id and its order follows the solution, which is not a
    contract this module should rely on.
    """
    hits = [(s, d) for s, d in sorted(dishes.items()) if predicate(s, d)]
    return ([h for h in hits if h[0] not in (exclude or set())]
            + [h for h in hits if h[0] in (exclude or set())])


# --------------------------------------------------------------------------
# the pairing rules, most specific first
# --------------------------------------------------------------------------

def pair_cooling(dishes, used=None) -> Optional[Pairing]:
    """A hot dish and the yogurt side that answers it.

    The most useful pairing on an Indian plate and the one a diner notices
    immediately when it is missing.
    """
    hot = _by(main_dishes(dishes), 'spice_level', HOT_SPICE, highest=True,
              exclude=used)
    if not hot:
        return None
    cool = _pick(dishes, _is_cooling, used)
    if not cool:
        return None
    hslot, hdish, hlevel = hot
    cslot, cdish = cool[0]
    level = SPICE_NAMES.get(int(hlevel), str(int(hlevel)))
    return Pairing(
        kind='cooling',
        detail=(f"{_pretty(hdish['name'])} is {level} — "
                f"{_pretty(cdish['name'])} cools it"),
        dishes=[hdish['name'], cdish['name']],
        slots=[hslot, cslot],
        evidence={'spice_level': int(hlevel), 'spice_name': level,
                  'cooling_slot': base_slot(cslot),
                  'cooling_protein': _text(cdish, 'primary_protein') or None},
    )


def pair_lightener(dishes, used=None) -> Optional[Pairing]:
    """A rich dish and something light enough to cut it."""
    rich = _by(main_dishes(dishes), 'richness_score', RICH_AT, highest=True,
               exclude=used)
    if not rich:
        return None
    light = _by(dishes, 'richness_score', LIGHT_AT, highest=False,
                exclude=(used or set()) | {rich[0]})
    if not light:
        return None
    rslot, rdish, rval = rich
    lslot, ldish, lval = light
    if rslot == lslot:
        return None
    return Pairing(
        kind='lightener',
        detail=(f"{_pretty(rdish['name'])} is rich at {int(rval)} of 5 — "
                f"{_pretty(ldish['name'])} at {int(lval)} cuts through it"),
        dishes=[rdish['name'], ldish['name']],
        slots=[rslot, lslot],
        evidence={'rich_score': int(rval), 'light_score': int(lval),
                  'scale_max': 5},
    )


def pair_crunch(dishes, used=None) -> Optional[Pairing]:
    """Something with bite, on a plate that is mostly soft.

    Gated on the plate actually BEING soft: `saucy` is 2,823 of 6,135 Bangalore
    rows, so most plates lean that way, but on a varied one a crisp dish is not
    relief and saying so would be flattery.
    """
    m = main_dishes(dishes)
    textures = [_text(d, 'texture') for d in m.values()]
    known = [t for t in textures if t]
    if not known:
        return None
    soft = sum(1 for t in known if t in SOFT_TEXTURES)
    share = soft / len(known)
    if share < SOFT_SHARE_FOR_RELIEF:
        return None
    crisp = _pick(dishes, lambda s, d: _text(d, 'texture') == CRISP, used)
    if not crisp:
        return None
    cslot, cdish = crisp[0]
    return Pairing(
        kind='crunch',
        detail=(f"{soft} of {len(known)} dishes are soft or saucy — "
                f"{_pretty(cdish['name'])} is the crisp one"),
        dishes=[cdish['name']],
        slots=[cslot],
        evidence={'soft_count': soft, 'scored_dishes': len(known),
                  'soft_share': round(share, 2), 'texture': CRISP},
    )


def pair_carrier(dishes, used=None) -> Optional[Pairing]:
    """A gravy and the bread or rice it is eaten with.

    The most basic structure on the plate, so it is last of the specific rules
    and only reported once — a reader who wants it stated has it, and it never
    crowds out the pairings they could not have predicted.
    """
    saucy = _pick(main_dishes(dishes),
                  lambda s, d: _text(d, 'texture') == SAUCY, used)
    carriers = _pick(dishes,
                     lambda s, d: _text(d, 'texture') in CARRIER_TEXTURES, used)
    if not saucy or not carriers:
        return None
    sslot, sdish = saucy[0]
    cslot, cdish = carriers[0]
    return Pairing(
        kind='carrier',
        detail=(f"{_pretty(sdish['name'])} is saucy — "
                f"{_pretty(cdish['name'])} carries it"),
        dishes=[sdish['name'], cdish['name']],
        slots=[sslot, cslot],
        evidence={'saucy_count': len(saucy), 'carrier_count': len(carriers),
                  'carrier_texture': _text(cdish, 'texture')},
    )


def pair_dry_against_saucy(dishes, used=None) -> Optional[Pairing]:
    """One dry vegetable beside one saucy one — the two-veg structure.

    `veg_dry_north_south_pair` and the nonveg compositions both aim at this, so
    when it holds it is worth saying that it held.
    """
    m = main_dishes(dishes)
    dry = _pick(m, lambda s, d: _text(d, 'texture') == DRY, used)
    saucy = _pick(m, lambda s, d: _text(d, 'texture') == SAUCY, used)
    if not dry or not saucy:
        return None
    dslot, ddish = dry[0]
    sslot, sdish = saucy[0]
    return Pairing(
        kind='contrast',
        detail=(f"{_pretty(ddish['name'])} is dry against "
                f"{_pretty(sdish['name'])} in sauce"),
        dishes=[ddish['name'], sdish['name']],
        slots=[dslot, sslot],
        evidence={'dry_count': len(dry), 'saucy_count': len(saucy)},
    )


ALL_PAIRINGS: List[Callable[..., Optional[Pairing]]] = [
    pair_cooling,
    pair_lightener,
    pair_crunch,
    pair_dry_against_saucy,
    pair_carrier,
]


def _gaps(dishes: Dict[str, Dict[str, Any]],
          found: List[Pairing]) -> List[str]:
    """What the plate is MISSING — the half that makes this a diagnostic.

    Only stated where the plate gives real grounds for it: a hot dish with no
    yogurt anywhere, or rich dishes with nothing light. Silence otherwise, so a
    gap line means something when it appears.
    """
    kinds = {p.kind for p in found}
    out: List[str] = []
    m = main_dishes(dishes)
    if 'cooling' not in kinds:
        hot = _by(m, 'spice_level', HOT_SPICE, highest=True)
        if hot and not any(_is_cooling(s, d) for s, d in dishes.items()):
            out.append(f"{_pretty(hot[1]['name'])} is "
                       f"{SPICE_NAMES.get(int(hot[2]), int(hot[2]))} and there "
                       f"is no curd or raita on the plate")
    if 'lightener' not in kinds:
        rich = _by(m, 'richness_score', RICH_AT, highest=True)
        if rich and _by(dishes, 'richness_score', LIGHT_AT, highest=False) is None:
            out.append(f"{_pretty(rich[1]['name'])} is rich at "
                       f"{int(rich[2])} of 5 and nothing on the plate is light")
    return out


def build_pairings(dishes: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """`{slot: attrs}` -> the complements on this plate, and what it lacks.

    A rule that raises is skipped rather than taking the request down, for the
    same reason `run_checks` does it: this describes a menu and must never be
    why one fails to render.
    """
    found: List[Pairing] = []
    used: set = set()
    for fn in ALL_PAIRINGS:
        try:
            p = fn(dishes, used)
        except Exception:  # pragma: no cover - defensive
            continue
        if p is None:
            continue
        # Every line has to introduce a dish nobody has read about yet.
        # Without this the rules pile up on whichever dish scores extremely:
        # a real Tuesday plate had `veg_fried_rice` nominated as the day's RICH
        # dish and then, two lines later, as its crisp RELIEF — both readings
        # true of the columns and flatly contradictory as advice. Dropping the
        # second is right whichever of the two is wrong, because a claim whose
        # every dish has already been discussed adds nothing either way.
        if used and not (set(p.slots) - used):
            continue
        found.append(p)
        used |= set(p.slots)
    # Guarded for the same reason each rule is: `_gaps` reads the same dish
    # dicts, so anything that can break a rule can break the gap scan too, and
    # this must never be why a menu fails to render.
    try:
        gaps = _gaps(dishes, found)
    except Exception:  # pragma: no cover - defensive
        gaps = []
    if found:
        summary = (f"{len(found)} pairing(s) hold this plate together"
                   + (f"; {len(gaps)} gap(s)" if gaps else ''))
    elif gaps:
        summary = 'nothing on this plate offsets it: ' + '; '.join(gaps)
    else:
        summary = 'not enough recorded texture, spice or richness to pair on'
    return {
        'summary': summary,
        'pairings': [p.to_dict() for p in found],
        'gaps': gaps,
    }
