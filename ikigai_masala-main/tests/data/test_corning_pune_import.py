"""Corning Chakan's Pune menu, imported into the Pune ontology.

The first client menu imported into a city other than Bangalore or Chennai, and
the first Maharashtrian list — so these tests pin the judgements that reading
took, because a re-import through `normalize_city_ontology.py` would drop them
silently:

* only the plated lunch and dinner rows are read — breakfast, evening snacks and
  midnight snacks are separate services the tool does not plan;
* the salad BAR is not a salad slot: its components are ingredients, and its
  composed chaats are starters;
* three printed rows serve two slots each and are split by dish name;
* the chutney row names an ingredient where it means a chutney;
* the one unlabelled block is read from dish names, never from position;
* Pune stays all-veg and every row stays `common`.
"""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.import_corning_pune_menu import (
    CATEGORY_MAP,
    FESTIVAL_COURSES,
    ITEM_COURSE,
    PUNE,
    SALAD_BAR_COMPONENTS,
    SOURCE_ALIASES,
    SPEC,
    clean_name,
    parse_source,
    refile,
)
from scripts.menu_import import build


def _norm(v) -> str:
    return str(v).strip().lower()


@pytest.fixture(scope="module")
def pune():
    df = pd.read_excel(PUNE)
    df.columns = [c.strip() for c in df.columns]
    return df


@pytest.fixture(scope="module")
def raw():
    return parse_source(verbose=False)


class TestOnlyThePlatedServiceIsRead:

    def test_the_grid_yields_the_lunch_and_dinner_rows(self, raw):
        assert any(k.startswith("LUNCH||") for k in raw)
        assert any(k.startswith("DINNER||") for k in raw)

    @pytest.mark.parametrize("label", ["breakfast", "evening snacks",
                                       "midnight snacks", "dressings", "tea",
                                       "accompaniment"])
    def test_the_other_services_are_never_imported(self, label):
        """A wada pav is breakfast, not the day's starter."""
        assert not [k for k in CATEGORY_MAP if k.split("||", 1)[1] == label]

    def test_the_salad_bar_continuation_rows_are_dropped(self, raw):
        """The five rows under SALAD are always components. Their `+` keys are
        absent from the category map, which is what skips them."""
        continuations = [k for k in raw if k.endswith("+")]
        assert continuations, "the continuation rows were not even parsed"
        for key in continuations:
            assert key not in CATEGORY_MAP, key

    def test_the_labelled_salad_row_is_read(self, raw):
        assert raw.get("LUNCH||salad"), "the composed chaats would be lost"


class TestTheSaladBarIsNotASaladSlot:

    def test_no_bare_vegetable_became_a_dish(self, pune):
        """A menu printing "Tomato" as the day's salad is useless, and it is the
        `remove_generic_rows.py` problem arriving by a new route."""
        names = set(pune["item"].map(_norm))
        assert not (names & SALAD_BAR_COMPONENTS), names & SALAD_BAR_COMPONENTS

    def test_the_chaats_it_carries_are_starters(self, pune):
        """Which is also the pool Pune most needed — it had 7 starters."""
        by_item = dict(zip(pune["item"].map(_norm),
                           pune["course_type"].map(_norm)))
        for dish in ("papadi_chaat", "samosa_chaat", "dhokla_chaat",
                     "kachori_chaat", "dahi_wada"):
            assert by_item.get(dish) == "starter", (dish, by_item.get(dish))

    def test_refile_sends_a_chaat_out_of_the_salad_slot(self):
        assert refile("papadi_chaat", "salad") == "starter"
        assert refile("kachumber_salad", "salad") == "salad"


class TestOneRowTwoSlots:

    def test_a_soup_in_the_dal_row_lands_in_soup(self):
        assert refile("cream_of_burnt_garlic_soup", "dal") == "soup"
        assert refile("dal_tadka", "dal") == "dal"

    def test_a_rasam_in_the_dal_row_lands_in_rasam(self):
        assert refile("rassam", "dal") == "rasam"

    def test_the_dessert_soup_row_splits_by_name(self):
        assert refile("palak_soup", "dessert") == "soup"
        assert refile("gulab_jamun", "dessert") == "dessert"

    def test_the_tetra_pack_row_splits_drinks_from_soups(self):
        assert refile("amul_sweet_lassi", "soup") == "welcome_drink"
        assert refile("masala_milk", "soup") == "welcome_drink"
        assert refile("tomato_soup", "soup") == "soup"

    def test_the_chutney_row_yields_pickle_and_raita_too(self):
        assert refile("pickle", "chutney") == "pickle"
        assert refile("dahi_raita_with_tadka", "chutney") == "curd_side"
        assert refile("tomato_chutney", "chutney") == "chutney"

    def test_landed_dishes_are_where_those_rules_put_them(self, pune):
        by_item = dict(zip(pune["item"].map(_norm),
                           pune["course_type"].map(_norm)))
        assert by_item.get("amul_sweet_lassi") == "welcome_drink"
        assert by_item.get("masala_milk") == "welcome_drink"
        assert by_item.get("dahi_raita_with_tadka") == "curd_side"
        assert by_item.get("burnt_garlic_soup") == "soup"


class TestTheChutneyRowNamesAnIngredient:

    def test_a_bare_ingredient_gains_the_category_word(self, pune):
        """It writes `Tomato` and `Tomato Chutney` on different days for the same
        thing. Without this the ontology gains a row called `tomato`."""
        names = set(pune["item"].map(_norm))
        for bare in ("tomato", "onion", "ginger", "til", "jawas"):
            assert bare not in names, bare
        assert "tomato_chutney" in names
        assert "onion_chutney" in names

    def test_it_folded_into_the_chutney_pune_already_had(self, pune):
        """`schezwan` was written bare; Pune already carries `schezwan_chutney`,
        so naming it properly re-tags that row instead of adding a second."""
        assert list(pune["item"].map(_norm)).count("schezwan_chutney") == 1
        assert "schezwan" not in set(pune["item"].map(_norm))


class TestTheUnlabelledBlockIsReadByName:

    def test_position_is_never_used(self, raw):
        """The Independence Day menu sits below the grid with no row labels, so
        the course comes from the dish NAME and the key is rewritten to match."""
        assert "SPECIAL||festival" not in SPEC.parse()

    def test_its_dishes_landed_in_the_course_their_names_say(self, pune):
        by_item = dict(zip(pune["item"].map(_norm),
                           pune["course_type"].map(_norm)))
        for dish, course in (("tiranga_pulao", "rice"),
                             ("dal_sunheri", "dal"),
                             ("ghee_paratha", "bread"),
                             ("tiranga_burfi", "dessert"),
                             ("colorful_papad", "papad"),
                             ("paneer_gulnaz_pasanda", "veg_gravy")):
            assert by_item.get(dish) == course, (dish, by_item.get(dish))

    def test_every_adjudicated_course_is_one_the_map_accepts(self):
        for item, course in FESTIVAL_COURSES.items():
            assert f"SPECIAL||{course}" in CATEGORY_MAP, (item, course)


class TestTheDuplicatesTheSourceWritesTwice:

    @pytest.mark.parametrize("dropped,kept", sorted(SOURCE_ALIASES.items()))
    def test_only_the_kept_spelling_is_in_the_ontology(self, pune, dropped, kept):
        names = list(pune["item"].map(_norm))
        if dropped == kept:                      # an entry kept for its course
            return
        assert dropped not in names, f"{dropped} should have folded into {kept}"

    def test_the_word_order_pairs_collapsed_to_one_row(self, pune):
        """`DUM ALOO KASHMIRI` and `KASHMIRI DUM ALOO` are one dish, and both
        arrive new in the same import so the evidence-based fold cannot settle
        them against the ontology."""
        names = list(pune["item"].map(_norm))
        for pair in (("dum_aloo_kashmiri", "kashmiri_dum_aloo"),
                     ("lasooni_palak", "palak_lasooni"),
                     ("malai_kofta", "malai_kofta_curry"),
                     ("babycorn_mushroom", "babycorn_mushroom_masala")):
            present = [n for n in pair if n in names]
            assert len(present) == 1, (pair, present)

    def test_the_source_junk_is_stripped(self):
        assert clean_name("ACHARI PANEER R") == "achari_paneer"
        assert clean_name("R PAPAD") == "roasted_papad"

    def test_mysore_pak_folds_onto_the_dish_the_ontology_has(self, pune):
        """Under the source's wording it is a unique name, so no other city can
        settle its `dessert_form` and the dessert variety rule cannot group it."""
        assert clean_name("Mysore Pak in Pure Ghee") == "ghee_mysore_pak"
        assert "mysore_pak_in_pure_ghee" not in set(pune["item"].map(_norm))


class TestAMisfiledCombinationCannotReachTheBreadSlot:

    def test_a_gravy_split_out_of_the_chapati_cell_is_a_gravy(self, pune):
        """"CHAPATI + MIX VEG" splits into two dishes; without the override the
        one-dish-one-category pass claims `mix_veg` for `bread` and the ontology
        gains a mixed-veg gravy servable as the day's roti."""
        assert ITEM_COURSE["mix_veg"] == "veg_gravy"
        assert refile("mix_veg", "bread") == "veg_gravy"
        by_item = dict(zip(pune["item"].map(_norm),
                           pune["course_type"].map(_norm)))
        assert by_item.get("mix_veg") == "veg_gravy"

    def test_pav_is_a_bread(self, pune):
        by_item = dict(zip(pune["item"].map(_norm),
                           pune["course_type"].map(_norm)))
        assert by_item.get("pav") == "bread"


class TestThePuneConventionsStillHold:

    def test_every_row_is_common(self, pune):
        """Pune's file is the whole city universe, and Pune is not in
        `FULL_POOL_CITIES` — a dish tagged `Corning Chakan` would be invisible to
        every Pune client, this one included."""
        assert set(pune["client"].map(_norm)) == {"common"}

    def test_the_city_is_still_all_veg(self, pune):
        proteins = {p for p in pune["primary_protein"].dropna().map(_norm) if p}
        assert not (proteins & {"chicken", "mutton", "fish", "prawn", "egg",
                                "lamb", "crab"}), sorted(proteins)

    def test_the_veg_kheema_dishes_did_not_become_chicken(self, pune):
        """`keema` maps to chicken in the shared protein vocabulary, and a
        non-veg dish in a veg slot is dropped from the pool by `_nonveg_mask` —
        the dish becomes unservable rather than merely mislabelled."""
        rows = pune[pune["item"].map(_norm).isin({"veg_kheema", "soya_kheema"})]
        assert len(rows) == 2
        assert not [p for p in rows["primary_protein"].dropna().map(_norm) if p]

    def test_no_duplicate_names_or_ids(self, pune):
        assert not pune["item"].duplicated().any()
        assert not pune["item_id"].duplicated().any()

    def test_the_pools_it_was_meant_to_deepen_actually_grew(self, pune):
        """Pune had no chutney and no papad rows at all, and 7 starters."""
        counts = pune["course_type"].map(_norm).value_counts()
        assert counts.get("chutney", 0) >= 10
        assert counts.get("papad", 0) >= 5
        assert counts.get("starter", 0) >= 12
        assert counts.get("veg_gravy", 0) >= 100
        assert counts.get("veg_dry", 0) >= 90


class TestRunningItAgainChangesNothing:

    def test_a_second_import_adds_and_retags_nothing(self, pune):
        frame = pune.copy()
        new, retag, _report, _log = build(frame, SPEC.parse(), SPEC)
        assert len(new) == 0, sorted(new["item"])[:8]
        assert retag == 0
