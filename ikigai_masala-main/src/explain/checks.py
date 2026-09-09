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

# `non_dal_protein` asks a question that only makes sense on a vegetarian
# plate. A day carrying chicken and egg is not protein-thin, and 59 of the
# fleet's 85 counters (69%) run a `nonveg_main` slot — so reading only the
# vegetarian half made the majority configuration flag for nothing.
NONVEG_PROTEINS = frozenset({
    'chicken', 'mutton', 'fish', 'egg', 'prawn', 'seafood', 'lamb', 'crab',
})

# `key_ingredient` values that name no ingredient. `mixed_vegetables` is 375
# Bangalore rows — CLAUDE.md records it as the de-facto default for a mixed
# salad — so two dishes "sharing" it is a gap in the data, not an echo on the
# plate. Reported as unknown rather than counted either way: calling it a pass
# would be as wrong as calling it a repeat.
GENERIC_INGREDIENTS = frozenset({
    'mixed_vegetables', 'mixed_veg', 'assorted', 'vegetable', 'vegetables',
    'mixed', 'other', 'seasonal_vegetables',
})

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

def check_colour_variety(dishes, target: Optional[int] = None,
                         slots: Optional[Any] = None) -> Check:
    """Distinct colours on the plate, against the target the SOLVER used.

    This check mirrors a rule the solver already enforces, and for a while it
    mirrored it wrongly — in both halves.

    *The dish set.* `MAIN_COURSES` is a fixed seven courses; the solver counts
    `cfg.color_slots`, which includes `dessert` and excludes `bread`. Two
    different questions under one name. Pass `slots` and this counts what the
    solver counted.

    *The target.* Hardcoding 4 ignores the solver's clamp (design note 13):
    `min(configured, colour-slots-configured, colour-cells-today,
    colours-present)`. A counter with three colour slots is legitimately asked
    for three, satisfies that, and was then flagged for not reaching four — a
    false alarm the chef cannot act on, because acting would break the rule
    that generated the menu. The 31% flag rate in the calibration run is mostly
    this. Given `target` (the counter's configured minimum), the day-level part
    of the clamp is reproduced here, since the number of colour dishes actually
    served is visible on the plate.

    With neither argument this keeps the old fixed behaviour, so a caller that
    has no `SolverConfig` in scope is unchanged.
    """
    counted = (main_dishes(dishes) if slots is None else
               {s: d for s, d in dishes.items() if base_slot(s) in set(slots)})
    c = _counter(counted, 'item_color')
    n = len(c)
    want = MIN_DISTINCT_COLOURS if target is None else int(target)
    # The solver clamps to the cells it actually has that day; so do we.
    effective = max(1, min(want, len(counted)))
    return Check(
        name='colour_variety',
        passed=n >= effective,
        detail=(f"{n} distinct colours across {sum(c.values())} dishes"
                f" (target {effective}+)"),
        evidence={'distinct': n, 'spread': dict(c), 'threshold': effective,
                  'configured_target': want, 'counted_dishes': len(counted)},
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

    **Only asked of a vegetarian plate.** The first version read only the
    vegetarian half of `primary_protein`, so a day serving chicken and egg
    beside a toor dal came back "dal is the only vegetarian protein" — true as
    written, and useless as a verdict, because the plate is not protein-thin.
    59 of the fleet's 85 counters run a `nonveg_main`, so that was the majority
    configuration flagging for nothing. A day with a non-veg main now skips.
    """
    m = main_dishes(dishes)
    prots = set(_counter(m, 'primary_protein'))
    nonveg = sorted(prots & NONVEG_PROTEINS)
    veg = sorted(p for p in prots if p in VEG_PROTEINS)
    non_dal = sorted(p for p in veg if p not in DAL_PROTEINS)
    if nonveg:
        return Check(
            name='non_dal_protein',
            passed=True,
            detail=f"the plate carries a non-vegetarian main ({', '.join(nonveg)})",
            evidence={'veg_proteins': veg, 'non_dal': non_dal,
                      'nonveg_proteins': nonveg, 'skipped': True},
        )
    return Check(
        name='non_dal_protein',
        passed=bool(non_dal),
        detail=(f"vegetarian protein: {', '.join(non_dal)}" if non_dal
                else 'dal is the only vegetarian protein on the plate'),
        evidence={'veg_proteins': veg, 'non_dal': non_dal,
                  'nonveg_proteins': [], 'skipped': False},
    )


def check_no_ingredient_echo(dishes) -> Check:
    """The same key ingredient twice on one plate.

    Legal today: a paneer gravy and a paneer dry differ in course_type, colour
    and texture, so nothing stops the solver taking both.

    **Sentinel values abstain.** `mixed_vegetables` is 375 Bangalore rows and
    names no ingredient, so two dishes carrying it tells you the ontology has a
    gap, not that the plate echoes. Counting it as a repeat is a false flag;
    counting it as a pass hides the gap. It is reported separately as
    `unknown`.

    This check was written off as the weakest of the six on a 64% false-
    positive rate. That number came from attributing the repeats to nearby
    rules rather than checking whether the solver had a choice — see the note
    at the top of `docs/explain_layer_calibration.md`. Measured against pool
    availability, the chicken repeats had 32 non-chicken dry dishes available
    (25% of the pool) and the wheat repeats had 210 non-wheat breads (63%).
    They are avoidable repeats, and this is the strongest check in the set.
    """
    m = main_dishes(dishes)
    c = _counter(m, 'key_ingredient')
    unknown = sorted(k for k in c if k in GENERIC_INGREDIENTS)
    repeats = {k: v for k, v in c.items()
               if v > 1 and k not in GENERIC_INGREDIENTS}
    detail = ('no ingredient repeats' if not repeats else
              'repeated: ' + ', '.join(f'{k} x{v}'
                                       for k, v in sorted(repeats.items())))
    if unknown:
        detail += f" ({len(unknown)} dish group(s) carry no named ingredient)"
    return Check(
        name='no_ingredient_echo',
        passed=not repeats,
        detail=detail,
        evidence={'repeats': repeats, 'distinct': len(c), 'unknown': unknown},
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


ALL_CHECKS: List[Callable[..., Check]] = [
    check_colour_variety,
    check_texture_contrast,
    check_spice_arc,
    check_non_dal_protein,
    check_no_ingredient_echo,
    check_richness_balance,
]

# Which verdicts are fit to put in front of a chef. Everything else still runs
# and still appears in the API response — this gates only what the UI renders
# as a judgement, so a known-wrong verdict is not spent on someone's first and
# only look at the feature.
#
#   texture_contrast   — measures something no rule enforces, on a column that
#                        is 99.2% populated. Its 16% flag rate has NOT been
#                        re-derived against pool availability; it is here
#                        because nothing contradicts it, not because it is
#                        proven.
#   no_ingredient_echo — re-derived against pool availability: the solver had
#                        32 non-chicken dry dishes and 210 non-wheat breads and
#                        repeated anyway. Sentinels now abstain.
#   non_dal_protein    — the non-veg false-positive class is fixed; the
#                        question is now only asked of a vegetarian plate.
#
# Deliberately absent: `colour_variety` (mirrors a solver rule and its flag
# rate has not been re-measured since the target was corrected), `spice_arc`
# and `richness_balance` (thresholds too loose to earn a line — see
# `docs/explain_layer_calibration.md`). Widen this set as each is measured.
CALIBRATED = frozenset({
    'texture_contrast', 'no_ingredient_echo', 'non_dal_protein',
})


def run_checks(dishes: Dict[str, Dict[str, Any]],
               only: Optional[List[str]] = None,
               calibrated_only: bool = False,
               colour_target: Optional[int] = None,
               colour_slots: Optional[Any] = None) -> List[Check]:
    """Run every check over one day's `{slot: attrs}`.

    A check that raises is skipped rather than taking the request down — this
    describes a menu, it must never be the reason one fails to render.

    `calibrated_only` keeps the uncalibrated verdicts out of a rendered
    judgement without removing them from the response, so the numbers stay
    available to whoever is calibrating them.
    """
    extra = {check_colour_variety: {'target': colour_target,
                                    'slots': colour_slots}}
    out: List[Check] = []
    for fn in ALL_CHECKS:
        try:
            c = fn(dishes, **extra.get(fn, {}))
        except Exception:  # pragma: no cover - defensive
            continue
        if only is not None and c.name not in only:
            continue
        if calibrated_only and c.name not in CALIBRATED:
            continue
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
