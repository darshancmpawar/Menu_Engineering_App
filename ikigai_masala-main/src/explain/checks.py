"""Deterministic plate-balance verdicts.

No LLM, no I/O, no pandas. Everything here is a pure function over plain dicts,
so a verdict can be pinned in a unit test without a solver, a database or a
network — the same way `test_freshness_variety.py` pins the recency map.

These verdicts are the ONLY claims the explanation layer is allowed to make.
Downstream, `api/explain_llm.py` hands them to a model to phrase nicely and then
rejects any sentence containing a number or dish name that did not originate
here. That is what stops the feature inventing rationale.

Two of the six checks catch things no existing menu rule sees:

  * `texture_contrast` — five saucy dishes on one plate satisfies every current
    constraint and every diner notices it is mushy.
  * `no_ingredient_echo` — a paneer gravy beside a paneer dry is legal today
    (different course_type, different colour) and reads as lazy.

The other four restate constraints the solver already enforces or implies. They
are reported rather than re-enforced: this module never changes a menu, it only
describes one.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Callable, Dict, List, Optional
import collections

# Courses that make up "the plate". Condiments, drinks and the fixed rice/papad
# stations are excluded — a welcome drink's colour says nothing about whether
# lunch works, and including `white_rice` would put a white dish on every single
# day and flatten the colour verdict into noise.
MAIN_COURSES = frozenset({
    'starter', 'rice', 'bread', 'veg_dry', 'veg_gravy', 'dal', 'nonveg_main',
})

# `spice_level` is stored 0-3. Names are for humans reading the bullets.
SPICE_NAMES = {0: 'mild', 1: 'medium', 2: 'hot', 3: 'very hot'}

# Vegetarian protein sources, as they appear in `primary_protein`. Used by
# `non_dal_protein` to answer "is there protein here that is not just dal?".
DAL_PROTEINS = frozenset({
    'toor_dal', 'moong_dal', 'urad_dal', 'chana_dal', 'masoor_dal',
    'mixed_dal', 'lentil',
})
VEG_PROTEINS = frozenset({
    'chickpea', 'paneer', 'soy', 'green_peas', 'black_eyed_pea', 'peanut',
    'yogurt', 'mushroom', 'kidney_bean', 'tofu', 'sprouts', 'cottage_cheese',
}) | DAL_PROTEINS

# --- thresholds -------------------------------------------------------------
# Tune these against a chef's judgement, not against intuition. Twenty days of
# rendered bullets in front of someone who plans menus for a living will move
# these numbers more usefully than any amount of reasoning here.
MIN_DISTINCT_COLOURS = 4      # mirrors the city colour rule
MIN_DISTINCT_TEXTURES = 3
MAX_ONE_TEXTURE_SHARE = 0.60  # >60% of the plate sharing one texture = mushy
MIN_MEAN_RICHNESS = 1.5
MAX_MEAN_RICHNESS = 3.5


@dataclass(frozen=True)
class Check:
    """One verdict. `detail` is the human sentence; `evidence` is the raw counts.

    `detail` is what a model may paraphrase. `evidence` exists so the validator
    can confirm every number in the generated prose came from somewhere real.
    """
    name: str
    passed: bool
    detail: str
    evidence: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def base_slot(slot: str) -> str:
    """`veg_dry__2` -> `veg_dry`. Slot ids carry a `__n` suffix when a counter
    asks for more than one of a course."""
    return str(slot).split('__')[0]


def main_dishes(dishes: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """The subset of `{slot: attrs}` that counts as the plate."""
    return {s: d for s, d in dishes.items() if base_slot(s) in MAIN_COURSES}


def _counter(dishes: Dict[str, Dict[str, Any]], key: str) -> collections.Counter:
    """Count non-empty values of `key` across dishes.

    Missing and blank values are skipped rather than counted as a category —
    a dish with no recorded texture must not create a phantom seventh texture
    and accidentally satisfy `texture_contrast`.
    """
    c: collections.Counter = collections.Counter()
    for d in dishes.values():
        v = d.get(key)
        if v is None:
            continue
        s = str(v).strip().lower()
        if s and s not in ('nan', 'none'):
            c[s] += 1
    return c


def _numbers(dishes: Dict[str, Dict[str, Any]], key: str) -> List[float]:
    out: List[float] = []
    for d in dishes.values():
        v = d.get(key)
        if v is None:
            continue
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            continue
    return out


# --------------------------------------------------------------------------
# the six checks
# --------------------------------------------------------------------------

def check_colour_variety(dishes) -> Check:
    m = main_dishes(dishes)
    c = _counter(m, 'item_color')
    n = len(c)
    return Check(
        name='colour_variety',
        passed=n >= MIN_DISTINCT_COLOURS,
        detail=(f"{n} distinct colours across {sum(c.values())} main dishes"
                f" (target {MIN_DISTINCT_COLOURS}+)"),
        evidence={'distinct': n, 'spread': dict(c),
                  'threshold': MIN_DISTINCT_COLOURS},
    )


def check_texture_contrast(dishes) -> Check:
    """A plate needs something saucy, something dry and something with bite.

    This is the check with no existing equivalent in the ruleset. `saucy` is
    2,942 of 6,143 Bangalore rows, so an unconstrained solve drifts toward an
    all-gravy plate without ever violating a rule.
    """
    m = main_dishes(dishes)
    c = _counter(m, 'texture')
    total = sum(c.values())
    if not total:
        return Check('texture_contrast', True, 'no texture data for this day',
                     {'spread': {}, 'total': 0})
    top_name, top_n = c.most_common(1)[0]
    share = top_n / total
    passed = len(c) >= MIN_DISTINCT_TEXTURES and share <= MAX_ONE_TEXTURE_SHARE
    return Check(
        name='texture_contrast',
        passed=passed,
        detail=(f"{len(c)} textures across {total} dishes; "
                f"{top_n} of {total} are {top_name}"),
        evidence={'distinct': len(c), 'spread': dict(c), 'total': total,
                  'dominant': top_name, 'dominant_count': top_n,
                  'dominant_share': round(share, 2),
                  'max_share': MAX_ONE_TEXTURE_SHARE},
    )


def check_spice_arc(dishes) -> Check:
    m = main_dishes(dishes)
    levels = _numbers(m, 'spice_level')
    if not levels:
        return Check('spice_arc', True, 'no spice data for this day',
                     {'spread': {}})
    named = collections.Counter(
        SPICE_NAMES.get(int(v), str(int(v))) for v in levels
    )
    return Check(
        name='spice_arc',
        passed=len(named) >= 2,
        detail=('spice runs ' + ', '.join(f'{k} x{v}' for k, v in named.most_common())),
        evidence={'spread': dict(named), 'distinct': len(named)},
    )


def check_non_dal_protein(dishes) -> Check:
    """Is there vegetarian protein here beyond the dal?

    A day whose only veg protein is toor dal is technically fed and practically
    thin, and it is invisible to every existing rule.
    """
    m = main_dishes(dishes)
    prots = set(_counter(m, 'primary_protein'))
    veg = sorted(p for p in prots if p in VEG_PROTEINS)
    non_dal = sorted(p for p in veg if p not in DAL_PROTEINS)
    return Check(
        name='non_dal_protein',
        passed=bool(non_dal),
        detail=(f"vegetarian protein: {', '.join(non_dal)}" if non_dal
                else 'dal is the only vegetarian protein on the plate'),
        evidence={'veg_proteins': veg, 'non_dal': non_dal},
    )


def check_no_ingredient_echo(dishes) -> Check:
    """The same key ingredient twice on one plate.

    Legal today: a paneer gravy and a paneer dry differ in course_type, colour
    and texture, so nothing stops the solver taking both.
    """
    m = main_dishes(dishes)
    c = _counter(m, 'key_ingredient')
    repeats = {k: v for k, v in c.items() if v > 1}
    return Check(
        name='no_ingredient_echo',
        passed=not repeats,
        detail=('no ingredient repeats' if not repeats else
                'repeated: ' + ', '.join(f'{k} x{v}' for k, v in sorted(repeats.items()))),
        evidence={'repeats': repeats, 'distinct': len(c)},
    )


def check_richness_balance(dishes) -> Check:
    m = main_dishes(dishes)
    vals = _numbers(m, 'richness_score')
    if not vals:
        return Check('richness_balance', True, 'no richness data for this day',
                     {'mean': None})
    mean = sum(vals) / len(vals)
    return Check(
        name='richness_balance',
        passed=MIN_MEAN_RICHNESS <= mean <= MAX_MEAN_RICHNESS,
        detail=f"average richness {mean:.1f} on a 0-5 scale across {len(vals)} dishes",
        evidence={'mean': round(mean, 2), 'n': len(vals),
                  'min_ok': MIN_MEAN_RICHNESS, 'max_ok': MAX_MEAN_RICHNESS},
    )


ALL_CHECKS: List[Callable[[Dict[str, Dict[str, Any]]], Check]] = [
    check_colour_variety,
    check_texture_contrast,
    check_spice_arc,
    check_non_dal_protein,
    check_no_ingredient_echo,
    check_richness_balance,
]


def run_checks(dishes: Dict[str, Dict[str, Any]],
               only: Optional[List[str]] = None) -> List[Check]:
    """Run every check over one day's `{slot: attrs}`.

    A check that raises is skipped rather than taking the request down — this
    describes a menu, it must never be the reason one fails to render.
    """
    out: List[Check] = []
    for fn in ALL_CHECKS:
        try:
            c = fn(dishes)
        except Exception:  # pragma: no cover - defensive
            continue
        if only is None or c.name in only:
            out.append(c)
    return out


def plate_profile(dishes: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """The raw distributions, independent of any pass/fail judgement.

    Kept separate from `run_checks` so the numbers survive a threshold change.
    """
    m = main_dishes(dishes)
    rich = _numbers(m, 'richness_score')
    spice = _numbers(m, 'spice_level')
    return {
        'main_dish_count': len(m),
        'colour_spread': dict(_counter(m, 'item_color')),
        'texture_spread': dict(_counter(m, 'texture')),
        'spice_spread': dict(collections.Counter(
            SPICE_NAMES.get(int(v), str(int(v))) for v in spice)),
        'protein_spread': dict(_counter(m, 'primary_protein')),
        'cuisine_spread': dict(_counter(m, 'cuisine_family')),
        'mean_richness': round(sum(rich) / len(rich), 2) if rich else None,
    }
