"""Render an EvidencePack as plain text. No model involved.

This is the product in steps 1-3: ship it, put it in front of a chef, and tune
`checks.py` thresholds against what they say before adding any prose.

It is also the permanent fallback. If the LLM is disabled, unreachable, slow, or
returns something the validator rejects, this is what the user sees. A menu must
never fail to render because an explanation did.
"""

from __future__ import annotations

from typing import Any, Dict, List

_TICK = '[ok]'
_FLAG = '[!]'

#: How many sentences an overview may run to. Four or five — long enough to
#: name two or three real pairings, short enough that someone reads all of it
#: before service.
MAX_OVERVIEW_SENTENCES = 5


def day_overview(pack: Dict[str, Any]) -> str:
    """A short paragraph about the day's menu: what goes with what.

    **An overview, not a checklist.** `render_day` below lists every verdict,
    which is the right shape for someone auditing the ruleset and the wrong one
    for someone reading a menu: a column of `[ok] texture contrast` lines says
    nothing about the food. This says "gobi 65 is very hot — boondi raita cools
    it", which is a sentence about two dishes a chef recognises.

    Built from `pairings`, because those are already statements about a PAIR
    with a reason attached; the checks score the plate as a set and leave the
    reader to work out what four colours means for lunch.

    Honest, though — a gap is named in the same voice as a pairing ("nothing
    here cools it"), not as a failed check. An overview that only reports good
    news is the thing a kitchen stops reading, and a missing yogurt beside a
    hot curry is the one item on this page they can fix this morning.

    Deterministic and model-free: this is the product, not a fallback for one.
    """
    pairings = pack.get('pairings') or {}
    found = list(pairings.get('pairings') or [])
    gaps = list(pairings.get('gaps') or [])
    profile = pack.get('plate_profile') or {}

    out: List[str] = []

    # 1. What the day IS. Theme and size, so the rest has something to attach to.
    weekday = str(pack.get('weekday') or '').strip()
    theme = str(pack.get('theme') or '').strip()
    n = profile.get('main_dish_count') or 0
    who = weekday or str(pack.get('date') or 'This day')
    if theme and theme != 'mix':
        out.append(f"{who} is a {theme} menu of {n} main dishes.")
    else:
        out.append(f"{who} runs {n} main dishes.")

    # 2-4. The pairings themselves — the point of the paragraph. Each `detail`
    #      already names two dishes and the reason, so it is used verbatim
    #      rather than paraphrased: the wording is what the evidence supports.
    room = MAX_OVERVIEW_SENTENCES - 1 - (1 if gaps else 0)
    for p in found[:max(1, room)]:
        detail = str(p.get('detail') or '').strip()
        if detail:
            out.append(detail[0].upper() + detail[1:] + '.')

    # 5. What it lacks. Last, and never dropped to make room for more praise.
    if gaps:
        out.append('Missing: ' + '; '.join(str(g) for g in gaps[:2]) + '.')
    elif not found:
        out.append(
            'There is not enough recorded texture, spice or richness on these '
            'dishes to say what pairs with what.'
        )

    return ' '.join(out[:MAX_OVERVIEW_SENTENCES])


def _profile_line(profile: Dict[str, Any]) -> str:
    bits: List[str] = []
    colours = profile.get('colour_spread') or {}
    textures = profile.get('texture_spread') or {}
    spice = profile.get('spice_spread') or {}
    if colours:
        bits.append(f"{len(colours)} colours")
    if textures:
        bits.append(f"{len(textures)} textures")
    if spice:
        bits.append('spice ' + '/'.join(spice))
    mean = profile.get('mean_richness')
    if mean is not None:
        bits.append(f"avg richness {mean}")
    return ', '.join(bits)


def render_day(pack: Dict[str, Any], *, show_passing: bool = True) -> List[str]:
    """One day -> a list of text lines.

    Failing checks are always shown. That is deliberate: the point of this layer
    is that it stays honest when the menu is mediocre, and a summary that only
    reports good news teaches people to ignore it.
    """
    lines: List[str] = []
    head = f"{pack.get('weekday') or ''} {pack.get('date')}".strip()
    if pack.get('theme'):
        head += f" - {pack['theme']}"
    lines.append(head)

    profile = _profile_line(pack.get('plate_profile') or {})
    if profile:
        lines.append(f"  Plate: {profile}")

    for c in pack.get('checks') or []:
        if c.get('passed') and not show_passing:
            continue
        mark = _TICK if c.get('passed') else _FLAG
        label = str(c.get('name', '')).replace('_', ' ')
        lines.append(f"  {mark} {label:<20} {c.get('detail','')}")

    # What works WITH what, and what the plate lacks. Before provenance: "why
    # this dish" is per-dish, this is about the meal, and the meal is the
    # question a chef asked first.
    pairings = pack.get('pairings') or {}
    for p in pairings.get('pairings') or []:
        lines.append(f"  + {str(p.get('kind','')):<10} {p.get('detail','')}")
    for gap in pairings.get('gaps') or []:
        lines.append(f"  {_FLAG} {'gap':<10} {gap}")

    for p in pack.get('provenance') or []:
        lines.append(f"  - {p.get('dish',''):<28} {p.get('detail','')}")

    for r in pack.get('relaxations') or []:
        rule = r.get('rule') or 'a rule'
        lines.append(f"  {_FLAG} relaxed: {rule} - {r.get('detail','')}")
        # The count alone is not actionable — WHICH days a floor was relaxed on
        # is the part a kitchen can do something about, so the extra renderings
        # are listed rather than summed away. `samples[0]` is already the
        # `detail` line above.
        for extra in (r.get('samples') or [])[1:]:
            lines.append(f"      also: {extra}")
        left = int(r.get('occurrences') or 1) - len(r.get('samples') or [1])
        if left > 0:
            lines.append(f"      ...and {left} more like it")

    return lines


def render_plan(packs: List[Dict[str, Any]], *, show_passing: bool = True) -> str:
    out: List[str] = []
    for p in packs:
        out.extend(render_day(p, show_passing=show_passing))
        out.append('')
    return '\n'.join(out).rstrip()


def day_summary(pack: Dict[str, Any]) -> str:
    """A single sentence for a table cell or tooltip.

    Leads with failures when there are any — the exception is the information.
    """
    failed = [c for c in (pack.get('checks') or []) if not c.get('passed')]
    profile = pack.get('plate_profile') or {}
    n = profile.get('main_dish_count') or 0
    if failed:
        names = ', '.join(str(c['name']).replace('_', ' ') for c in failed)
        return f"{n} main dishes; check: {names}"
    return f"{n} main dishes; balanced on all {len(pack.get('checks') or [])} checks"
