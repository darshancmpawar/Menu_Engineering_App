"""A rule named `*_weekly` has to mean weekly on a plan longer than a week.

`selector_frequency`'s `max` counts across the WHOLE HORIZON. That is right for
a one-week plan and silently tightens as the plan grows: `max: 1` means "once a
fortnight" on 14 days and "once in three weeks" on 21. Sixty shipped rules are
named `*_weekly` or `*_once_per_week` and every one of them behaved that way.

`nonveg_biryani_weekly` was worse, because its key was already CALLED
`max_per_week` while summing over the horizon — the name promised the semantics
and the code did not deliver them. And it is the one most easily contradicted:
a biryani-theme day narrows a single-nonveg counter to biryani only, or
`nonveg_main_daily_pair` mandates one, so the second biryani day is FORCED
rather than chosen. Cap and themes then contradict each other and `/plan`
answers 422.

The effect was fleet-wide. At 7 days 74 of 85 counters diagnosed clean; at 14
days only 34, and almost every block named one of these rules. With per-week
caps it is 85 of 85.

Two halves have to agree or the bug comes back in a different shape: `apply()`
constrains per week, and `diagnose()` compares the busiest WEEK against the cap.
Comparing a horizon total against a weekly number is what made the rule read as
impossible; comparing per-week while constraining per-horizon would make a real
conflict invisible.
"""

from __future__ import annotations

import datetime as dt

import pytest

from src.menu_rules.selector_frequency_rule import SelectorFrequencyRule


def _rule(**cfg):
    base = {"name": "t", "type": "selector_frequency",
            "selector": {"flag": "is_x"}}
    base.update(cfg)
    return SelectorFrequencyRule(base)


class TestTheConfigContract:
    def test_max_per_week_can_stand_alone(self):
        assert _rule(max_per_week=1).validate_config()

    def test_a_negative_is_rejected(self):
        assert not _rule(max_per_week=-1).validate_config()

    def test_it_may_be_combined_with_an_absolute_ceiling(self):
        """`max_per_week` for the cadence, `max` for the whole plan."""
        assert _rule(max=2, max_per_week=1).validate_config()

    def test_a_weekly_cap_looser_than_the_horizon_cap_is_rejected(self):
        """`max_per_week: 2` under `max: 1` cannot both hold, and silently
        taking the tighter one would hide a config mistake."""
        assert not _rule(max=1, max_per_week=2).validate_config()

    def test_it_cannot_be_combined_with_exact(self):
        assert not _rule(exact=1, max_per_week=1).validate_config()

    def test_max_still_means_the_horizon(self):
        """The old key keeps its meaning — this is an addition, not a
        redefinition, so a rule that really is "once per plan" can say so."""
        r = _rule(max=1)
        assert r.max == 1 and r.max_per_week is None


class TestTheWeeklyFloor:
    """`min_per_week` is the twin of `max_per_week`, and exists for the same
    reason: `min` counts days across the horizon, so "at least one a week"
    written as `min: 1` becomes "once a fortnight" on 14 days.

    It replaces the retired `item_frequency` rule type, whose keys were already
    NAMED `min_per_week`/`max_per_week` while summing over the horizon — so
    Tekion's "one liquid rice a week" allowed one in twenty-five days while a
    `slot_composition` forced one every Thursday.
    """

    def test_it_can_stand_alone(self):
        assert _rule(min_per_week=1).validate_config()

    def test_a_negative_is_rejected(self):
        assert not _rule(min_per_week=-1).validate_config()

    def test_it_pairs_with_the_ceiling(self):
        """Both set to 1 is "exactly one per calendar week"."""
        assert _rule(min_per_week=1, max_per_week=1).validate_config()

    def test_a_floor_above_the_ceiling_is_rejected(self):
        assert not _rule(min_per_week=2, max_per_week=1).validate_config()

    def test_it_cannot_be_combined_with_exact(self):
        assert not _rule(exact=1, min_per_week=1).validate_config()

    def test_the_retired_rule_type_is_gone(self):
        """`item_frequency` was a strictly weaker duplicate — five selector
        keys against thirteen — carrying the horizon-summing bug. Both of its
        configs were migrated; leaving the type registered would let the next
        one reintroduce the defect."""
        from src.menu_rules.menu_rule_loader import MenuRuleLoader
        assert 'item_frequency' not in MenuRuleLoader.RULE_CLASSES

    def test_no_config_still_references_it(self):
        import json
        from pathlib import Path
        root = Path(__file__).resolve().parents[2] / "data" / "configs"
        bad = []
        for p in sorted(root.rglob("*.json")):
            d = json.loads(p.read_text(encoding="utf-8"))

            def walk(o, where=p.name):
                if isinstance(o, dict):
                    if o.get("type") == "item_frequency":
                        bad.append(f"{where}:{o.get('name')}")
                    for v in o.values():
                        walk(v, where)
                elif isinstance(o, list):
                    for v in o:
                        walk(v, where)
            walk(d)
        assert not bad, bad


class TestWeeksAreCalendarWeeks:
    """ISO Monday-Sunday, the same boundary `chinese_continental` resolves its
    parity on. A rolling 7-day window would be stricter than the client's own
    "once a week"; the calendar week is what a caterer means."""

    @pytest.mark.parametrize("start,days,weeks", [
        (dt.date(2026, 9, 7), 5, 1),    # Mon-Fri, one ISO week
        (dt.date(2026, 9, 7), 7, 1),    # Mon-Sun, still one
        (dt.date(2026, 9, 7), 8, 2),    # spills into the next
        (dt.date(2026, 9, 7), 14, 2),
        (dt.date(2026, 9, 7), 21, 3),
        (dt.date(2026, 9, 9), 5, 1),    # Wed-Sun, still one ISO week
        (dt.date(2026, 9, 10), 5, 2),   # Thu-Mon, crosses the boundary
    ])
    def test_iso_week_count_over_a_horizon(self, start, days, weeks):
        dates = [start + dt.timedelta(days=i) for i in range(days)]
        got = {(d.isocalendar()[0], d.isocalendar()[1]) for d in dates}
        assert len(got) == weeks

    def test_a_mid_week_start_may_allow_two_in_seven_days(self):
        """Stated so the looser reading is a decision on the record rather than
        a surprise: a calendar week is not a rolling window, so Thursday and the
        following Monday are different weeks."""
        a, b = dt.date(2026, 9, 10), dt.date(2026, 9, 14)
        assert (b - a).days < 7
        assert a.isocalendar()[1] != b.isocalendar()[1]


class TestTheShippedRulesMigrated:
    def test_no_weekly_named_rule_still_uses_a_horizon_max(self):
        """The whole point of the migration. A rule whose NAME says weekly and
        whose config says `max` is the bug this file exists for."""
        import json
        from pathlib import Path
        root = Path(__file__).resolve().parents[2] / "data" / "configs"
        offenders = []

        def check(rules, where):
            for r in rules or []:
                if r.get("type") != "selector_frequency":
                    continue
                name = r.get("name") or ""
                if ("weekly" in name or "per_week" in name) and "max" in r:
                    offenders.append(f"{where}:{name}")

        for p in sorted(root.rglob("*.json")):
            d = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(d, dict):
                continue
            if isinstance(d.get("rules"), list):
                check(d["rules"], p.name)
            for key, val in d.items():
                if isinstance(val, dict):
                    check(val.get("rules"), f"{p.name}:{key}")
                    for cname, cv in (val.get("counters") or {}).items():
                        if isinstance(cv, dict):
                            check(cv.get("rules"), f"{p.name}:{key}/{cname}")
        assert not offenders, offenders

    def test_the_biryani_cap_is_per_week_in_every_city(self):
        import json
        from pathlib import Path
        root = Path(__file__).resolve().parents[2] / "data" / "configs" / "city_rules"
        seen = 0
        for p in sorted(root.glob("*.json")):
            for r in json.loads(p.read_text(encoding="utf-8")).get("rules", []):
                if r.get("type") == "nonveg_biryani_weekly":
                    assert "max_per_week" in r, p.name
                    seen += 1
        assert seen


class TestTheTwoHalvesAgree:
    def test_apply_groups_by_week_and_diagnose_compares_by_week(self):
        """Read from the source rather than asserted behaviourally, because the
        failure mode is the two halves disagreeing — one per-week and the other
        per-horizon — which no single-horizon test can see."""
        from pathlib import Path
        src = Path(__file__).resolve().parents[2] / "src" / "menu_rules"
        for mod in ("selector_frequency_rule.py", "nonveg_rules.py"):
            text = (src / mod).read_text(encoding="utf-8")
            assert "isocalendar()" in text, mod
            assert "_forced_dates" in text, mod

    def test_composition_forcing_reports_dates_not_just_a_count(self):
        """A count cannot be bucketed by week. Most biryani forcing comes from
        `nonveg_main_daily_pair` rather than a biryani-only pool, so a
        count-only answer left the per-week check with nothing to bucket and it
        fell back to the horizon total."""
        from src.menu_rules.slot_composition_rule import (
            dates_forced_by_composition, days_forced_by_composition,
        )
        assert callable(dates_forced_by_composition)
        assert callable(days_forced_by_composition)
