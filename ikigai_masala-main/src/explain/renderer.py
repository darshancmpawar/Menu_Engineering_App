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
