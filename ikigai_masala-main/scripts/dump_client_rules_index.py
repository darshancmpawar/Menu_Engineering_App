#!/usr/bin/env python3
"""Generate `docs/client_rules_index.md` — every client's rules, in one place.

The per-client rules live in 43 files under `data/configs/clients/`, and the
sentences the client actually said live in each rule's `_comment`. Neither is
something you can read end to end, and answering "what is configured for
Bakertilly?" or "who has a chapati-only bread slot?" meant grepping JSON.

So this renders all of it as one Markdown table per client: the rule's name, a
one-line summary of what it constrains, and the client's own words where the
config records them. GENERATED — regenerate it rather than editing it, or it
becomes the third thing that can disagree with the configs.

    python scripts/dump_client_rules_index.py [--check]

`--check` verifies the committed file still matches the configs without writing,
which is what `tests/platform/test_client_rules_index.py` pins.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TARGET = ROOT / "docs" / "client_rules_index.md"

_HEADER = """# Client rules index

Every per-client rule the planner loads, one section per client.

**GENERATED — do not edit.** Run `python scripts/dump_client_rules_index.py`
after changing anything under `data/configs/clients/` and commit the diff;
`tests/platform/test_client_rules_index.py` fails if this file is stale.

## How to read a row

* **Rule** — the rule's `name`. A name that also exists in the city ruleset is an
  *override*: the client's keys are merged over the city rule's, so a rule listed
  here under a city rule's name changes that rule for this client only.
* **What it does** — the constraint, in one line. `≤ N days` / `≥ N days` /
  `exactly N days` count DAYS across the horizon, not dishes, so "≤ 1 day" for a
  two-dish station still allows two of that family on the one day it lands
  (`daily max` is the per-day cap).
* **Client's words** — the requirement as the client stated it, where the config
  records it. Absent means the rule was derived rather than quoted.

Rules that are *not* here are not unconfigured: most requirements are enforced by
the city ruleset (`data/configs/city_rules/<city>.json`), which every client in
that city inherits. See `docs/client_logics.md` (Bangalore),
`docs/pune_client_logic.md`, `docs/chennai_client_logic.md` and
`docs/ncr_client_logic.md` for the per-city reasoning, and `docs/pune_rulebook.md`
for the 70-rule Pune source.

"""


def _sel(sel: Any) -> str:
    """A selector dict as a short human phrase."""
    if not isinstance(sel, dict):
        return str(sel)
    if "any_of" in sel:
        return " or ".join(_sel(s) for s in sel["any_of"])
    if "all_of" in sel:
        return " and ".join(_sel(s) for s in sel["all_of"])
    if "any_flag" in sel:
        flags = sel["any_flag"]
        return " or ".join(str(f) for f in flags)
    if "name_contains" in sel:
        raw = sel["name_contains"]
        raw = raw if isinstance(raw, list) else [raw]
        return "named " + "/".join(str(x) for x in raw)
    for key in ("flag", "sub_category", "item", "key_ingredient",
                "primary_protein", "course_type", "cuisine_family"):
        if key in sel:
            val = sel[key]
            return str(val) if key == "flag" else f"{key} {val}"
    return json.dumps(sel)


def _slots(rule: Dict[str, Any], key: str = "base_slot") -> str:
    bs = rule.get(key)
    if not bs:
        return ""
    names = bs if isinstance(bs, list) else [bs]
    return " @ " + "/".join(str(n) for n in names)


def _counts(rule: Dict[str, Any]) -> List[str]:
    out = []
    if rule.get("exact") is not None:
        out.append(f"exactly {rule['exact']} day(s)")
    if rule.get("min") is not None:
        out.append(f"≥ {rule['min']} day(s)")
    if rule.get("max") is not None:
        out.append(f"≤ {rule['max']} day(s)")
    if rule.get("daily_max") is not None:
        out.append(f"≤ {rule['daily_max']} per day")
    if rule.get("daily_min") is not None:
        out.append(f"≥ {rule['daily_min']} per day")
    if rule.get("min_per_week") is not None:
        out.append(f"≥ {rule['min_per_week']}/week")
    if rule.get("max_per_week") is not None:
        out.append(f"≤ {rule['max_per_week']}/week")
    if rule.get("non_consecutive"):
        out.append("not on adjacent days")
    if rule.get("forbidden_weekdays"):
        days = ", ".join(str(d) for d in rule["forbidden_weekdays"])
        out.append(f"never on {days}")
    if rule.get("allowed_day_types"):
        themes = ", ".join(str(t) for t in rule["allowed_day_types"])
        out.append(f"only on {themes} days")
    return out


def _components(comps: Any) -> str:
    parts = []
    for c in comps or []:
        if not isinstance(c, dict):
            continue
        phrase = _sel(c.get("selector"))
        if c.get("exclude"):
            phrase += f" (not {_sel(c['exclude'])})"
        n = c.get("count", 1)
        parts.append(phrase if n == 1 else f"{n}× {phrase}")
    return " + ".join(parts)


def summarise(rule: Dict[str, Any]) -> str:
    """One line describing what *rule* constrains."""
    kind = rule.get("type", "")

    if kind == "selector_frequency":
        bits = _counts(rule) or ["no count"]
        text = f"{_sel(rule.get('selector'))}{_slots(rule)}: " + ", ".join(bits)
        if rule.get("exclude"):
            text += f" (excluding {_sel(rule['exclude'])})"
        if rule.get("allowed_day_types"):
            text += f"; only on {', '.join(rule['allowed_day_types'])} days"
        return text

    if kind == "selector_history_window":
        return (f"{_sel(rule.get('selector'))}{_slots(rule)}: once per "
                f"{rule.get('window_days')} days, read from saved history")

    if kind == "item_frequency":
        return f"{_sel(rule.get('selector'))}{_slots(rule)}: " + ", ".join(
            _counts(rule) or ["no count"])

    if kind == "slot_day_restriction":
        days = ", ".join(rule.get("allowed_weekdays") or [])
        return f"{rule.get('base_slot')} runs only on {days} (blank otherwise)"

    if kind == "slot_composition":
        gate = []
        if rule.get("min_slot_count") is not None:
            gate.append(f"≥{rule['min_slot_count']}")
        if rule.get("max_slot_count") is not None:
            gate.append(f"≤{rule['max_slot_count']}")
        if rule.get("requires_slot_count") is not None:
            gate.append(f"={rule['requires_slot_count']}")
        head = f"{rule.get('base_slot')} must include"
        if gate:
            head += f" (when the counter serves {' and '.join(gate)} of it)"
        parts = []
        if rule.get("components"):
            parts.append(_components(rule["components"]))
        for theme, comps in (rule.get("components_by_theme") or {}).items():
            parts.append(f"on a {theme} day: {_components(comps)}")
        for day, comps in (rule.get("components_by_weekday") or {}).items():
            parts.append(f"on {day}: {_components(comps)}")
        return f"{head}: " + "; ".join(parts)

    if kind == "repeatable_items":
        scope = str(rule.get("scope", "both")).lower()
        what = ("may repeat on any day" if scope == "both"
                else "may recur across plans, but stays distinct within one")
        return f"{_sel(rule.get('selector'))}{_slots(rule)}: {what}"

    if kind == "fixed_daily_item":
        return f"{_sel(rule.get('selector'))}{_slots(rule)}: the SAME dish every day"

    if kind == "ingredient_ban":
        return "never serve: " + ", ".join(rule.get("ingredients") or [])

    if kind == "same_day_exclusion":
        scope = "the same week" if rule.get("scope") == "week" else "the same day"
        return (f"{_sel(rule.get('selector'))} and {_sel(rule.get('exclude'))} "
                f"never share {scope}")

    if kind == "attribute_grouping":
        bits = []
        if rule.get("non_consecutive"):
            bits.append("no value on adjacent days")
        if rule.get("max_per_group") is not None:
            bits.append(f"each value ≤ {rule['max_per_group']} day(s)")
        return (f"{rule.get('base_slot')} grouped by {rule.get('group_by')}: "
                + ", ".join(bits or ["no constraint"]))

    if kind == "soft_preference":
        mode = rule.get("mode", "")
        pri = rule.get("priority", "medium")
        body = {
            "different_day": lambda: (f"keep {_sel(rule.get('selector_a'))} and "
                                      f"{_sel(rule.get('selector_b'))} on different days"),
            "avoid_consecutive": lambda: (f"avoid {_sel(rule.get('selector'))}"
                                          f"{_slots(rule)} on adjacent days"),
            "avoid_attribute_repeat": lambda: (f"vary {rule.get('group_by')}"
                                               f"{_slots(rule)} across the week"),
            "prefer_day_types": lambda: (f"prefer {_sel(rule.get('selector'))} on "
                                         f"{', '.join(rule.get('day_types') or [])} days"),
            "prefer_daily": lambda: f"prefer {_sel(rule.get('selector'))}{_slots(rule)} every day",
            "match_attribute": lambda: (
                f"{rule.get('base_slot_a')} and {rule.get('base_slot_b')} should "
                f"agree on {rule.get('group_by')} "
                f"({'/'.join(rule.get('values') or [])})"),
        }.get(mode, lambda: mode)
        return f"prefer ({pri}): {body()}"

    if kind == "theme_slot_filter":
        bits = []
        if rule.get("exempt_slots") is not None:
            bits.append("theme filter does not narrow: "
                        + ", ".join(rule["exempt_slots"]))
        if rule.get("indian_veg_dry_themes"):
            bits.append("veg dry stays Indian on: "
                        + ", ".join(rule["indian_veg_dry_themes"]))
        for theme, slots in (rule.get("indian_slots_by_theme") or {}).items():
            bits.append(f"on a {theme} day these stay Indian: {', '.join(slots)}")
        return "; ".join(bits) or "theme filter settings"

    if kind == "unique_items":
        return f"no repeats within a {rule.get('scope', 'plan')}"

    return kind or "(no type)"


def _quote(rule: Dict[str, Any]) -> str:
    text = str(rule.get("_comment") or "").strip()
    if not text:
        return ""
    # Only the client's own sentence is wanted, not the whole rationale: a
    # `_comment` opens with the quoted requirement and continues with why.
    for end in (".' ", ".” ", '." '):
        if end in text:
            text = text[: text.index(end) + 2]
            break
    else:
        text = text.split(". ")[0].strip()
        if len(text) > 200:
            text = text[:197] + "…"
    return text.strip().strip("'\"“”").strip().replace("|", "\\|")


def _constants(spec: Dict[str, Any]) -> List[str]:
    out = []
    for slot, val in (spec or {}).items():
        if str(slot).startswith("_"):
            continue
        if isinstance(val, dict):
            days = ", ".join(f"{d}={v}" for d, v in val.items()
                             if not str(d).startswith("_"))
            out.append(f"`{slot}` — {days}")
        elif isinstance(val, list):
            out.append(f"`{slot}` — {' / '.join(map(str, val))} "
                       f"(alternating by ISO week)")
        else:
            out.append(f"`{slot}` — {val}")
    return out


def render() -> str:
    from src.menu_rules import MenuRuleLoader
    from src.client.client_config import ClientConfigLoader  # noqa: F401

    blob = MenuRuleLoader()._read_client_blob()
    lines = [_HEADER]
    lines.append(f"**{len(blob)} clients have per-client rules.**\n\n")

    for client in sorted(blob, key=str.lower):
        entry = blob[client]
        if not isinstance(entry, dict):          # legacy bare list
            entry = {"rules": entry}
        lines.append(f"## {client}\n\n")
        note = str(entry.get("_comment") or "").strip()
        if note:
            lines.append(f"{note}\n\n")

        body = _render_block(entry)
        lines.extend(body)

        # Per-counter blocks. These were missing entirely, which made the index
        # wrong rather than merely thin: World Bank and ICON Chn keep most of
        # their logic here, and L&T and Siemens Technology already did.
        counters = entry.get("counters") or {}
        counter_body: List[str] = []
        for cname in sorted(counters, key=str.lower):
            cblock = counters[cname]
            if not isinstance(cblock, dict):
                continue
            inner = _render_block(cblock)
            if not inner:
                continue
            counter_body.append(f"### {client} → {cname}\n\n")
            cnote = str(cblock.get("_comment") or "").strip()
            if cnote:
                counter_body.append(f"{cnote}\n\n")
            counter_body.extend(inner)
        lines.extend(counter_body)

        if not body and not counter_body:
            lines.append("_No rules — the city ruleset covers this client._\n\n")

    return "".join(lines)


def _render_block(entry: Dict[str, Any]) -> List[str]:
    """The rules / disables / pins table for one client or counter block."""
    rows = []
    for ref in entry.get("use") or []:
        if isinstance(ref, str):
            name, base = ref, ref
            extra = {}
        else:
            base = ref.get("ref", "")
            name = ref.get("as", base)
            extra = ref.get("with") or {}
        detail = f"shelf component `{base}`"
        if extra:
            keys = ", ".join(f"`{k}`" for k in extra)
            detail += f", with {keys} overridden"
        rows.append((name, detail, ""))

    for rule in entry.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        rows.append((rule.get("name", "(unnamed)"),
                     summarise(rule), _quote(rule)))

    out: List[str] = []
    if rows:
        out.append("| Rule | What it does | Client's words |\n")
        out.append("|---|---|---|\n")
        for name, what, quote in rows:
            out.append(f"| `{name}` | {what} | {quote} |\n")
        out.append("\n")

    if entry.get("disable"):
        names = ", ".join(f"`{n}`" for n in entry["disable"])
        out.append(f"**City rules switched off:** {names}\n\n")

    consts = _constants(entry.get("constant_items") or {})
    if consts:
        out.append("**Pinned items:** " + "; ".join(consts) + "\n\n")

    excluded = entry.get("shared_categories_excluded_counters") or []
    if excluded:
        names = ", ".join(f"`{n}`" for n in excluded)
        out.append(f"**Not synced with the shared categories:** {names}\n\n")

    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="verify the committed file is current; write nothing")
    args = ap.parse_args()

    text = render()
    if args.check:
        current = TARGET.read_text() if TARGET.exists() else ""
        if current == text:
            print(f"{TARGET.relative_to(ROOT)} is up to date")
            return 0
        print(f"{TARGET.relative_to(ROOT)} is STALE — re-run "
              f"scripts/dump_client_rules_index.py")
        return 1
    TARGET.write_text(text)
    print(f"wrote {TARGET.relative_to(ROOT)} ({text.count(chr(10))} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
