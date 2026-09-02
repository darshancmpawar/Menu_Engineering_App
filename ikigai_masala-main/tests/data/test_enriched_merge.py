"""The client's enriched workbooks are MERGED into the city lists, not swapped in.

`scripts/merge_enriched_ontology.py` folds `<city>_enriched_final.xlsx` into
`data/raw/city_items/<city>.xlsx`. The uploads are a real improvement — colour
0% blank in all four, a `primary_protein` vocabulary, a 1-5 `richness_score`
where ours was 98% zeros, two columns the schema did not carry — and they are
branched from a snapshot taken before the last three commits, so a replacement
would silently undo work: NCR's vendor and calendar rows back in `veg_gravy`,
the `raitha` duplicates back, twenty-one course fixes reverted, 64 bare-integer
`item_id`s restored.

So the tests split by the three decisions that make it a merge:

* which columns cross over and in which DIRECTION (overwrite vs fill-blanks),
* what is deliberately NOT taken — their literal `none`, and any non-veg protein
  that would make a dish unservable,
* and that the pass is monotone and idempotent, so it can sit in the correction
  chain with everything else.
"""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.city_list import CITIES, city_path
from scripts.merge_enriched_ontology import (
    FILL_BLANKS, NEW_COLUMNS, OVERWRITE, SEEDED_FROM, _norm, _refused,
    enriched_path, load_enriched, merge,
)


@pytest.fixture(scope="module")
def frames():
    out = {}
    for city in CITIES:
        d = pd.read_excel(city_path(city))
        d.columns = [c.strip() for c in d.columns]
        out[city] = d
    return out


@pytest.fixture(scope="module")
def enriched():
    return {c: load_enriched(c) for c in CITIES if enriched_path(c).is_file()}


def _by_name(df):
    return {_norm(r["item"]): r for _, r in df.iterrows()}


class TestWhatNoneMeans:
    """The enriched files spell "this dish has no protein focus" as the literal
    string `none` — 4,073 of Bangalore's 6,143 rows, which is why their
    `primary_protein` is 0% blank where ours is 77%.

    That is presentation, not information. A blank already means the same thing
    to every consumer, and `none` would be a *matchable* value in a column
    `selector_frequency`, `ingredient_ban_rule` and `_nonveg_mask` all select
    on, where a rule naming it would read as a real ingredient.
    """

    @pytest.mark.parametrize("value", ["none", "None", "NONE", " none ",
                                       "", "nan", None])
    def test_norm_reads_it_as_blank(self, value):
        assert _norm(value) == ""

    @pytest.mark.parametrize("value", ["chicken", "paneer", "toor_dal"])
    def test_a_real_protein_is_not_blank(self, value):
        assert _norm(value) == value

    @pytest.mark.parametrize("city", CITIES)
    def test_no_city_list_carries_the_literal(self, frames, city):
        col = frames[city]["primary_protein"].fillna("").astype(str)
        assert not col.str.strip().str.lower().eq("none").any()


class TestTheColumnsThatCrossedOver:
    @pytest.mark.parametrize("col", NEW_COLUMNS)
    @pytest.mark.parametrize("city", CITIES)
    def test_the_new_columns_exist_everywhere(self, frames, city, col):
        """A column absent from one city's list is a column no rule can rely
        on, so the two arrive in ALL of them — Hyderabad included, which has no
        enriched workbook of its own."""
        assert col in frames[city].columns

    @pytest.mark.parametrize("city", CITIES)
    def test_the_schema_is_one_shape(self, frames, city):
        assert len(frames[city].columns) == 136
        assert list(frames[city].columns) == list(frames[CITIES[0]].columns)

    def test_the_reviewed_colour_won(self, frames, enriched):
        """`item_color` overwrites. Asserted as agreement across the whole
        column rather than on one dish, so it cannot pass on a lucky row."""
        live, src = _by_name(frames["bangalore"]), enriched["bangalore"]
        disagree = [n for n, row in live.items()
                    if n in src and _norm(src[n].get("item_color"))
                    and _norm(src[n]["item_color"]) != _norm(row["item_color"])]
        assert not disagree[:10], disagree[:10]

    def test_richness_is_no_longer_almost_all_zero(self, frames):
        """The reason it is in OVERWRITE: ours carried no information."""
        col = pd.to_numeric(frames["bangalore"]["richness_score"],
                            errors="coerce").fillna(0)
        assert (col > 0).mean() > 0.5

    def test_colour_is_complete_in_the_cities_the_client_reviewed(self, frames):
        """What the uploads were for. It was 15.7% blank in Bangalore, 35.7% in
        NCR — and a blank colour is not neutral: `_add_color_constraints` clamps
        a day's required distinct colours to the number PRESENT among the
        candidates, so blanks quietly relaxed the rule.

        The last three Bangalore blanks are dishes the client's pass DROPPED and
        we kept (`mixed_veg`, `sprouts`, `mixed_fruit_crush`), so no enriched
        colour reaches them; they are settled in
        `fill_item_colours.ADJUDICATED`."""
        for city in (c for c in CITIES if enriched_path(c).is_file()):
            blank = frames[city]["item_color"].fillna("").astype(str).str.strip()
            assert int(blank.eq("").sum()) == 0, city

    def test_the_seeded_city_is_the_one_exception_and_is_bounded(self, frames):
        """Hyderabad has no enriched workbook, so only its shared-with-Bangalore
        rows gain a colour by name; Quest's own 101 additions depend on
        `fill_item_colours` alone and some of them it will not guess.

        Stated as a bound rather than zero because inventing a colour is worse
        than leaving one blank — the blanks are already in
        `docs/colours_to_confirm_by_family.csv` for the client. Pinned so the
        number cannot grow quietly, and pinned per CITY so a regression in one
        of the four reviewed lists cannot hide inside this allowance."""
        blank = frames["hyderabad"]["item_color"].fillna("").astype(str).str.strip()
        n = int(blank.eq("").sum())
        assert n <= 60, n
        assert n / len(frames["hyderabad"]) < 0.02, n


class TestTheGuardAgainstAnUnservableDish:
    """`_refused` exists for one failure mode: the enriched pass reads
    `primary_protein` off the dish NAME, and a name can lie about it.

    `PoolBuilder.build_pools` drops every `_nonveg_mask` row from every slot
    outside `NONVEG_SLOTS`, so a `rice` row carrying `mutton` leaves the rice
    pool and never joins a non-veg one — the dish becomes UNSERVABLE, which is
    the structural break `audit_course_types.unservable_rows` exists to catch.
    """

    def test_a_meat_protein_is_refused_outside_the_nonveg_slots(self):
        row = pd.Series({"course_type": "rice", "item": "keema_veg_biryani"})
        assert _refused("primary_protein", "mutton", row)

    def test_it_is_accepted_on_a_nonveg_main_row(self):
        row = pd.Series({"course_type": "nonveg_main", "item": "mutton_curry"})
        assert not _refused("primary_protein", "mutton", row)

    def test_it_is_accepted_on_a_nonveg_soup_row(self):
        """There are TWO non-veg courses. Reading the singular `NONVEG_SLOT`
        instead of the `NONVEG_SLOTS` set refuses a chicken broth its own
        protein — Bangalore files 30 of them under `nonveg_soup`."""
        row = pd.Series({"course_type": "nonveg_soup", "item": "chicken_broth_soup"})
        assert not _refused("primary_protein", "chicken", row)

    def test_the_guard_reads_the_set_and_not_the_singular(self):
        """Pinned directly, because the two constants differ by one character
        and the singular is the one that reads correctly at a glance."""
        from src.constants import NONVEG_SLOT, NONVEG_SLOTS
        assert NONVEG_SLOT in NONVEG_SLOTS and len(NONVEG_SLOTS) > 1
        for slot in NONVEG_SLOTS:
            row = pd.Series({"course_type": slot, "item": "x"})
            assert not _refused("primary_protein", "chicken", row), slot

    def test_a_veg_protein_is_never_refused(self):
        row = pd.Series({"course_type": "veg_gravy", "item": "matar_paneer"})
        assert not _refused("primary_protein", "paneer", row)

    def test_only_that_column_is_guarded(self):
        """Everything else the enriched file offers is taken as given — the
        guard is about one specific way a value breaks the pools, not a general
        suspicion of the source."""
        row = pd.Series({"course_type": "rice", "item": "x"})
        for col in (*OVERWRITE, *FILL_BLANKS, *NEW_COLUMNS):
            if col == "primary_protein":
                continue
            assert not _refused(col, "chicken", row), col

    def test_the_two_real_rows_did_not_get_a_meat_protein(self, frames):
        """The rows that made the guard necessary. `keema_veg_biryani` is a VEG
        biryani (soya keema — the same trap twelve NCR keemas already
        document) and `red_velvet_pastry_egg_less` says so in its own name."""
        from src.constants import NONVEG_PROTEINS
        meat = {_norm(p) for p in NONVEG_PROTEINS}
        live = _by_name(frames["bangalore"])
        for name in ("keema_veg_biryani", "red_velvet_pastry_egg_less"):
            row = live.get(name)
            if row is None:
                continue           # renamed or folded since; nothing to check
            assert _norm(row["primary_protein"]) not in meat, name

    def test_no_city_list_holds_an_unservable_row(self, frames):
        """The general form of the same statement, over every city — and over
        the `NONVEG_SLOTS` set, since a chicken broth in `nonveg_soup` is
        perfectly servable."""
        from src.constants import NONVEG_PROTEINS, NONVEG_SLOTS
        meat = {_norm(p) for p in NONVEG_PROTEINS}
        keep = {_norm(s) for s in NONVEG_SLOTS}
        for city in CITIES:
            d = frames[city]
            bad = d[
                d["primary_protein"].map(_norm).isin(meat)
                & ~d["course_type"].map(_norm).isin(keep)
            ]
            assert bad.empty, (city, sorted(bad["item"].astype(str))[:5])

    def test_a_planted_lie_is_refused(self, frames):
        """So the guard cannot pass because nothing happens to trip it."""
        d = frames["bangalore"].head(50).copy()
        d["course_type"] = "rice"
        d["primary_protein"] = ""
        src = {_norm(r["item"]): {"primary_protein": "chicken"}
               for _, r in d.iterrows()}
        out, stats = merge(d, src)
        assert stats["primary_protein"] == 0
        assert len(stats["refused"]) == len(d)
        assert out["primary_protein"].map(_norm).eq("").all()


class TestTheMergeIsSafeToRunInTheChain:
    def test_a_second_merge_changes_nothing(self, frames, enriched):
        """Idempotent, so it can sit at the head of the correction chain and be
        re-run after any import without drifting."""
        for city, src in enriched.items():
            _out, stats = merge(frames[city], src)
            changed = sum(v for k, v in stats.items()
                          if k not in ("unmatched", "refused"))
            assert changed == 0, (city, stats)

    def test_fill_blanks_does_not_overwrite(self, frames, enriched):
        """The direction that matters: `cuisine_family` carries adjudicated
        verdicts (the NCR north-chicken retag) and `primary_protein` drives
        `_nonveg_mask`, so a value we derived definitionally must stand."""
        d = frames["ncr"].copy()
        for col in FILL_BLANKS:
            d[col] = d[col].astype(object)
            d[col] = "SENTINEL"
        out, _stats = merge(d, enriched["ncr"])
        for col in FILL_BLANKS:
            assert out[col].eq("SENTINEL").all(), col

    def test_the_seeded_city_takes_its_values_from_its_donor(self, frames):
        """Hyderabad has no enriched workbook — it did not exist when the client
        was given the files — so the values reach it from the merged Bangalore
        list by dish name."""
        assert SEEDED_FROM.get("hyderabad") == "bangalore"
        assert not enriched_path("hyderabad").is_file()
        blr, hyd = _by_name(frames["bangalore"]), _by_name(frames["hyderabad"])
        shared = sorted(set(blr) & set(hyd))
        assert len(shared) > 1000, len(shared)
        for name in shared[:400]:
            assert _norm(hyd[name]["item_color"]) == _norm(blr[name]["item_color"]), name
