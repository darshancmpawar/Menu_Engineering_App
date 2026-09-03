"""`cuisine_family` is complete enough that a themed day can see its pool.

A blank is not neutral. `ThemeSlotFilterRule.pre_filter_pool` narrows a
cuisine-main slot with `pool[pool['cuisine_family'] == target]`, so a blank
matches no target and the dish is dropped from every themed day. NCR was 62.9%
blank while the other four cities were complete, and every NCR client themes
most or all of its weekdays — so 613 rows sat in the pool, passed every
diagnostic, and were filtered out before the solver saw them.

The tests below are split by what they protect:

* the FILL is still there and still monotone,
* the vote still REFUSES what it should — the two values that make a dish
  theme-day-only, and the attributes that are genuinely regionless,
* and the two tiers that beat the plain vote still beat it, because both exist
  to work around a specific defect and both would pass silently if removed.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from scripts.city_list import CITIES, city_path
from scripts.fill_cuisine_family import (
    MIN_AGREEMENT, MIN_ROWS, PREDICTABLE, SKIP_COURSES,
    exclusive_mask, region_from_sub_category,
)

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "docs" / "cuisines_to_confirm.csv"

#: The slots `ThemeSlotFilterRule` narrows by cuisine. A blank here is a ban.
CUISINE_MAIN = {"rice", "veg_gravy", "veg_dry", "starter", "nonveg_main"}


def _norm(s):
    return s.fillna("").astype(str).str.strip().str.lower().replace({"nan": ""})


@pytest.fixture(scope="module")
def frames():
    out = {}
    for city in CITIES:
        d = pd.read_excel(city_path(city))
        d.columns = [c.strip() for c in d.columns]
        out[city] = d
    return out


class TestTheColumnIsUsable:
    @pytest.mark.parametrize("city", [c for c in CITIES if c != "ncr"])
    def test_the_settled_cities_are_complete(self, frames, city):
        assert int(_norm(frames[city]["cuisine_family"]).eq("").sum()) == 0

    def test_ncr_is_no_longer_mostly_blank(self, frames):
        d = frames["ncr"]
        blank = int(_norm(d["cuisine_family"]).eq("").sum())
        assert blank < 300, (
            f"{blank} blank — the fill regressed. Re-run "
            f"scripts/fill_cuisine_family.py")

    def test_the_slots_the_theme_filter_gates_are_nearly_complete(self, frames):
        """The assertion that matters: a blank in one of these five slots is a
        dish the solver can never be offered on a themed day."""
        d = frames["ncr"]
        cm = _norm(d["course_type"]).isin(CUISINE_MAIN)
        blank = _norm(d["cuisine_family"]).eq("")
        assert int((cm & blank).sum()) < 100

    def test_a_north_themed_day_can_actually_fill_its_slots(self, frames):
        """Stated as what a counter needs rather than as a snapshot: under the
        20-day cooldown a count-1 slot needs roughly one distinct dish per
        working day in the window plus the week being planned."""
        d = frames["ncr"]
        cf = _norm(d["cuisine_family"])
        ct = _norm(d["course_type"])
        for slot in ("rice", "veg_gravy", "veg_dry", "nonveg_main"):
            n = int((ct.eq(slot) & cf.eq("north_indian")).sum())
            assert n >= 20, (slot, n)

    @pytest.mark.parametrize("city", CITIES)
    def test_only_the_known_vocabulary_is_used(self, frames, city):
        allowed = {"", "north_indian", "south_indian", "chinese", "continental",
                   "drink", "other"}
        seen = set(_norm(frames[city]["cuisine_family"]))
        assert seen <= allowed, seen - allowed


class TestWhatTheVoteRefuses:
    def test_it_can_only_propose_an_indian_region(self):
        """chinese and continental make a dish appear ONLY on its own theme day,
        so guessing one is strictly worse than leaving the row blank — a blank
        at least survives a mix day. No NCR client runs either day."""
        assert set(PREDICTABLE) == {"north_indian", "south_indian"}

    #: The two tiers that READ a field rather than inferring from one. Both
    #: deliberately beat the exclusive-flag skip: a row whose `sub_category`
    #: says `north` while a continental flag says otherwise is contradicting
    #: itself, and the sub_category is the half that names a region.
    EVIDENCE_TIERS = {"same dish in another city",
                      "sub_category names the region"}

    def test_the_vote_never_gives_a_theme_exclusive_row_a_region(self, frames):
        """A guessed region is worse than a blank for these rows: chinese and
        continental make a dish appear ONLY on their own theme day, while a
        blank at least survives a mix day. The flags are not clean enough to
        write from either — they agree with the column 89% and 94% of the time,
        under the 95% this pass demands.

        Scoped to the VOTE on purpose. The two tiers above it read a field
        instead of inferring from one, and the pass lets them answer an
        exclusive row; asserting "never filled" was broader than the code
        promises, and the first five rows planted on happened to have a
        `sub_category` that names a region. What has to hold is that anything
        which DID get filled was filled by evidence.

        The blank is PLANTED. It used to be taken from NCR's own leftovers and
        the client's enriched workbooks filled the last of them, so the test
        started failing with "nothing left to prove" — a guard going quiet
        because the data got better, which is the one way a guard must not go
        quiet. Planting asks the same question however complete the column
        becomes.
        """
        import scripts.fill_cuisine_family as F
        d = frames["ncr"].copy()
        m = exclusive_mask(d)
        assert int(m.sum()) > 0, "no theme-exclusive rows to reason about"

        d[F.COLUMN] = d[F.COLUMN].astype(object)
        planted = list(d.index[m])
        d.loc[planted, F.COLUMN] = ""
        names = {_norm(pd.Series([d.at[i, "item"]]))[0] for i in planted}

        rows = pd.concat([frames[c] for c in CITIES], ignore_index=True)
        known = rows[_norm(rows[F.COLUMN]) != ""]
        _out, filled, unresolved = F.apply(
            d, F.learn_by_dish(rows), F.learn(known), F.learn(known))

        guessed = [(n, v, why) for n, _ct, v, why in filled
                   if n in names and why not in self.EVIDENCE_TIERS]
        assert not guessed, guessed
        assert unresolved, "every exclusive row was answered by evidence — " \
                           "the skip is no longer reachable, so re-read it"
        assert any(why == "carries a chinese/continental flag"
                   for _n, _ct, why in unresolved)

    def test_an_ordinary_row_blanked_the_same_way_is_filled(self, frames):
        """The counter-check: the refusal has to be about the exclusive flags
        rather than about the planting.

        Deliberately NOT "and by the vote". Almost every NCR dish also exists
        in another city, so `learn_by_dish` — the strongest and cheapest tier —
        answers a planted NCR row before the vote is consulted, and demanding a
        vote fill here tests which tier happens to win rather than anything
        about the refusal. The vote's own thresholds are measured in
        `test_the_threshold_is_the_measured_one`."""
        import scripts.fill_cuisine_family as F
        d = frames["ncr"].copy()
        ordinary = list(d.index[
            ~exclusive_mask(d)
            & _norm(d["course_type"]).isin(CUISINE_MAIN)
            & _norm(d[F.COLUMN]).ne("")
        ][:200])
        assert ordinary, "no ordinary cuisine-main row to plant on"

        d[F.COLUMN] = d[F.COLUMN].astype(object)
        d.loc[ordinary, F.COLUMN] = ""
        rows = pd.concat([frames[c] for c in CITIES], ignore_index=True)
        known = rows[_norm(rows[F.COLUMN]) != ""]
        out, _filled, _ = F.apply(
            d, F.learn_by_dish(rows), F.learn(known), F.learn(known))
        refilled = int(_norm(out.loc[ordinary, F.COLUMN]).ne("").sum())
        assert refilled > len(ordinary) // 2, refilled

    def test_welcome_drinks_are_left_alone(self):
        """The corpus splits 331 `drink` / 139 `north_indian` for that course,
        so there is no convention to learn."""
        assert "welcome_drink" in SKIP_COURSES

    def test_the_threshold_is_the_measured_one(self):
        """Held out on a fifth of the 6,849 classified dishes, 6/0.95 scored
        96.5%. Lowering either without re-measuring is how a 92% rule ships."""
        assert (MIN_ROWS, MIN_AGREEMENT) == (6, 0.95)


class TestTheTwoTiersThatBeatTheVote:
    def test_a_sub_category_that_names_a_region_states_it(self):
        assert region_from_sub_category("chicken_north_masala") == "north_indian"
        assert region_from_sub_category("south_rice_bath") == "south_indian"
        assert region_from_sub_category("mixed_veg_curry") == ""

    def test_a_sub_category_naming_both_states_neither(self):
        assert region_from_sub_category("north_south_fusion") == ""

    def test_the_north_chicken_rows_got_their_region(self, frames):
        """Why that tier exists. Across the corpus `chicken_north_masala` reads
        46% north / 45% continental — not because it is ambiguous but because
        Bangalore tags 53 of its own such rows `continental` (the known defect
        in docs/pending_config_changes.md). The plain vote therefore refused it,
        leaving 64 NCR rows blank whose own sub_category says "north"."""
        d = frames["ncr"]
        m = _norm(d["sub_category"]).eq("chicken_north_masala")
        assert int(m.sum()) > 50
        # None is blank any more, and the overwhelming majority read north. The
        # handful that do not arrived carrying `south_indian` and the pass is
        # monotone, so it left them — `chicken_chettinad` really is south
        # Indian, which makes its sub_category the wrong half of that row.
        assert int(_norm(d["cuisine_family"])[m].eq("").sum()) == 0
        assert int(_norm(d["cuisine_family"])[m].eq("north_indian").sum()) >= 90

    def test_a_citys_own_convention_is_stronger_than_the_corpus(self, frames):
        """`mixed_veg_curry` reads 77% north across the corpus and is correctly
        refused as regionless; within NCR its own rows read 97% north, because
        Bangalore's south Indian cooking was diluting a North Indian city's
        convention. Measured at 97.5% against 96.5% held out per city."""
        d = frames["ncr"]
        m = _norm(d["sub_category"]).eq("mixed_veg_curry")
        filled = _norm(d["cuisine_family"])[m]
        assert int(m.sum()) > 100
        assert int(filled.eq("north_indian").sum()) / int(m.sum()) > 0.9

    def test_the_corpus_still_calls_that_attribute_regionless(self, frames):
        """The other half — if the pooled corpus ever agreed about
        `mixed_veg_curry`, the city-scoped tier would stop being the reason
        those rows are filled and this test would be passing vacuously."""
        rows = pd.concat(
            [frames[c] for c in CITIES if c != "hyderabad"], ignore_index=True)
        m = (_norm(rows["sub_category"]).eq("mixed_veg_curry")
             & _norm(rows["cuisine_family"]).ne(""))
        share = _norm(rows["cuisine_family"])[m].value_counts(normalize=True)
        assert share.iloc[0] < MIN_AGREEMENT


class TestTheResidueIsReported:
    def test_the_report_exists_and_matches(self, frames):
        assert REPORT.is_file()
        report = pd.read_csv(REPORT)
        blank = int(_norm(frames["ncr"]["cuisine_family"]).eq("").sum())
        assert len(report) == blank

    def test_every_reported_row_says_why(self):
        report = pd.read_csv(REPORT)
        assert report["why_not_filled"].notna().all()
        assert set(report["why_not_filled"]) <= {
            "no evidence", "carries a chinese/continental flag",
            "course has no agreed convention"}


class TestItIsMonotone:
    def test_a_second_run_fills_nothing(self, tmp_path, monkeypatch):
        """Run against COPIES so the committed workbooks are never at risk."""
        import shutil
        import scripts.fill_cuisine_family as F

        for city in CITIES:
            shutil.copyfile(city_path(city), tmp_path / f"{city}.xlsx")
        monkeypatch.setattr(F, "CITY_DIR", tmp_path)
        monkeypatch.setattr(F, "REPORT", tmp_path / "report.csv")

        before = {c: pd.read_excel(tmp_path / f"{c}.xlsx") for c in CITIES}
        F.main()
        for city in CITIES:
            after = pd.read_excel(tmp_path / f"{city}.xlsx")
            a = before[city].fillna("").astype(str)
            b = after.fillna("").astype(str)
            assert a.equals(b), city
