"""Hyderabad's item list: what Quest's menu added, and what seeding cost.

`hyderabad.xlsx` is the first city workbook SEEDED from another city's rather
than built from a raw list, so the tests split in two.

**What the import added** — the Telugu vegetable and Telangana chicken
vocabulary the Bangalore fallback lacked. Not the whole Hyderabadi repertoire:
Bangalore's list is pan-Indian and already carries bagara rice, mirchi ka salan,
the pappu family, andhra kodi koora and double ka meetha, so the tests below name
only dishes actually verified absent from it.

**What seeding cost** — three things that only bite because ~6,000 of the 6,260
rows are Bangalore's:

1. Every one of those rows carries a BANGALORE client's pool token, which names
   a site in another city. Hyderabad must be in `FULL_POOL_CITIES` or a client
   sees `common` alone.
2. The corpus the all-cities correction scripts learn from doubled without
   gaining a fact, so `complete_ontology` and `fill_item_colours` now dedupe by
   dish. Pinned here as well as in their own tests because the *reason* is
   Hyderabad.
3. The eight rows `audit_course_types` adjudicated for Bangalore came along, so
   the same verdicts have to hold here.

The counts below are floors, not snapshots — stated as what a slot needs to
survive the 20-day item cooldown (roughly one distinct dish per working day in
the window plus the week being planned), which is the question that actually
decides whether a menu can be generated. A pinned exact count breaks the next
time a client menu is legitimately imported.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.constants import FULL_POOL_CITIES
from src.ontology.paths import CITY_ITEMS_DIR, city_excel_path, city_required_slots

ROOT = Path(__file__).resolve().parents[2]

#: A count-1 slot under the default 20-day cooldown needs about this many
#: distinct dishes to still have a legal candidate in week two.
COOLDOWN_FLOOR = 15


@pytest.fixture(scope="module")
def hyd():
    df = pd.read_excel(CITY_ITEMS_DIR / "hyderabad.xlsx")
    df.columns = [c.strip() for c in df.columns]
    return df


@pytest.fixture(scope="module")
def blr():
    df = pd.read_excel(CITY_ITEMS_DIR / "bangalore.xlsx")
    df.columns = [c.strip() for c in df.columns]
    return df


def _names(df):
    return set(df["item"].astype(str).str.strip().str.lower())


def _course(df, course):
    return df[df["course_type"].astype(str).str.strip().str.lower() == course]


class TestTheCityHasItsOwnList:
    def test_it_no_longer_falls_back_to_bangalore(self):
        assert city_excel_path("Hyderabad") == str(
            CITY_ITEMS_DIR / "hyderabad.xlsx")

    def test_the_workbook_is_the_master_schema(self, hyd, blr):
        """A column absent from the reference list cannot exist in a city's."""
        assert len(hyd.columns) == 134
        assert list(hyd.columns) == list(blr.columns)

    def test_it_is_not_declared_in_ontology_categories(self):
        """Deliberate. Seeded from Bangalore, it covers every mandatory slot, so
        the undeclared default — require them ALL — is the stricter check.
        Declaring it would only lower the bar."""
        assert city_required_slots("Hyderabad") is None

    def test_every_mandatory_slot_builds(self):
        """What the line above buys: this is the check that would fail."""
        from src.ontology.repository import OntologyRepository
        _df, pools = OntologyRepository().menu_data("Hyderabad")
        empty = [slot for slot, items in pools.items() if len(items) == 0]
        assert not empty, empty

    def test_ids_and_names_are_unique(self, hyd):
        assert not hyd["item_id"].duplicated().any()
        dup = hyd[hyd.duplicated(["item", "course_type"], keep=False)]
        assert dup.empty, sorted(set(dup["item"]))[:10]


class TestSeedingIsWhyItIsAFullPoolCity:
    def test_hyderabad_plans_from_the_whole_list(self):
        assert "hyderabad" in FULL_POOL_CITIES

    def test_most_rows_are_tagged_to_another_city_s_clients(self, hyd):
        """The concrete reason. These tokens name Bangalore sites; no Hyderabad
        client will ever select one, so without the switch every client resolves
        to `common` alone."""
        tokens = hyd["client"].fillna("").astype(str).str.lower()
        foreign = tokens.str.contains("healthineers|citrix|booking|cloudera")
        assert int(foreign.sum()) > len(hyd) // 2

    def test_common_alone_would_be_a_fraction_of_the_list(self, hyd):
        tokens = hyd["client"].fillna("").astype(str).str.lower()
        common_only = tokens.str.split(",").apply(
            lambda ts: {t.strip() for t in ts} == {"common"})
        assert int(common_only.sum()) < len(hyd) // 2

    def test_the_full_list_is_what_a_client_actually_gets(self):
        from src.ontology.repository import OntologyRepository
        repo = OntologyRepository()
        whole, _ = repo.menu_data("Hyderabad")
        narrowed, _ = repo.filtered_menu_data("Hyderabad", [])
        assert len(narrowed) == len(whole)


@pytest.fixture(scope="module")
def added(hyd, blr):
    """Only the rows this import created — every assertion about what Quest
    contributed has to be scoped to these, or it is really an assertion about
    Bangalore's list. Three of my first drafts were: `banana`, `bagara_rice` and
    `pulihora`-adjacent names are all Bangalore rows that came with the seed."""
    return hyd[~hyd["item"].astype(str).str.strip().str.lower().isin(_names(blr))]


class TestWhatQuestAdded:
    #: Verified absent from `bangalore.xlsx`. Deliberately NOT `bagara_rice`,
    #: `salan`, `pappu` or `kodi_kura` — the seed already carries all four, and
    #: asserting them would pass without the import having run.
    TELUGU = ["pulihora", "vankaya_kura", "dosakaya_pappu", "kodi_pulusu",
              "thotakura_pappu", "inti_kodi_kura"]

    @pytest.mark.parametrize("dish", TELUGU)
    def test_the_regional_dishes_are_present(self, added, dish):
        assert dish in _names(added), dish

    @pytest.mark.parametrize("dish", TELUGU)
    def test_the_seed_did_not_already_have_them(self, blr, dish):
        """The other half: if Bangalore carried it, the assertion above would
        hold whether or not this import ever ran."""
        assert dish not in _names(blr), dish

    def test_it_is_a_strict_superset_of_the_seed(self, hyd, blr):
        """Nothing may be LOST in the seeding. `expand_side_pools` used to drop
        four (`sambaram`, `pretzel`, `a2b_juice`, `tea_cake`): its un-share pass
        read every blocklisted name in a non-master city as a bad cross-city
        share, which is true of a city built from its own list and false of one
        seeded from the master."""
        assert _names(hyd) > _names(blr)

    def test_the_count_is_the_import_s_own(self, added):
        assert len(added) == 101

    def test_the_new_rows_carry_the_quest_pool_token(self, added):
        tokens = added["client"].fillna("").astype(str).str.lower()
        assert tokens.str.contains("quest").all()

    def test_no_placeholder_became_a_dish(self, added):
        """"Chef Choice Desserts" is printed on 14 of the 41 days and is not a
        dish — a menu showing it tells the diner nothing and no colour or
        ingredient rule can reason about it."""
        assert not [n for n in _names(added) if "chef" in n and "choice" in n]

    def test_the_fruit_row_was_not_imported(self, added):
        """`fruit` is not a base slot, and the source's values are serving counts
        ("Banana 2 nos", "Apple 1 nos") rather than dishes."""
        names = _names(added)
        assert not (names & {"banana", "apple", "orange", "papaya",
                             "watermelon", "musk_melon"})

    def test_serving_counts_were_stripped_from_names(self, added):
        """The source writes portions into the dish name. Left in, the same
        laddu written without one becomes a second row."""
        import re
        bad = [n for n in _names(added) if re.search(r"_?\d+_?nos?$", n)]
        assert not bad, bad

    def test_the_staples_were_skipped(self, added):
        """Steamed rice, yoghurt and raita are printed every single day and are
        const-slot staples the city list already holds."""
        assert not (_names(added) & {"steamed_rice", "steam_rice", "yoghurt",
                                     "yogurt", "curd", "raita", "raitha"})


class TestTheNonVegRowsCanActuallyBePlaced:
    """A non-veg dish with no form flag is never chosen — it sits in the pool
    and `nonveg_main_daily_pair` cannot place it (`nonveg_structural_flags`)."""

    FORM_FLAGS = ["is_nonveg_dry", "is_nonveg_gravy", "is_nonveg_biryani"]

    def test_every_quest_nonveg_row_has_a_form(self, hyd, blr):
        new = hyd[~hyd["item"].astype(str).str.strip().str.lower()
                  .isin(_names(blr))]
        nv = new[new["course_type"].astype(str).str.strip().str.lower()
                 == "nonveg_main"]
        assert len(nv) >= 15, "the import should have added a real non-veg block"
        flags = nv[self.FORM_FLAGS].apply(
            pd.to_numeric, errors="coerce").fillna(0)
        formless = nv[flags.sum(axis=1) == 0]
        assert formless.empty, sorted(formless["item"])

    def test_the_biryani_row_settled_the_two_pulaos(self, hyd):
        """Neither name says "biryani", so the NAME heuristic rightly refused
        both. The source printed them in its biryani row, which is the evidence
        — the same argument `style_by_label` makes for dry vs gravy."""
        rows = hyd[hyd["item"].astype(str).str.strip().str.lower()
                   .isin({"andhra_chicken_pulao", "hyderabadi_dum_pulao"})]
        assert len(rows) == 2, sorted(rows["item"])
        flags = rows[["is_nonveg_biryani", "is_biryani_item"]].apply(
            pd.to_numeric, errors="coerce").fillna(0)
        assert (flags == 1).all().all()

    def test_the_dry_and_gravy_rows_split(self, hyd):
        """Both forms have to exist or the daily pair has nothing to compose."""
        nv = _course(hyd, "nonveg_main")
        num = nv[["is_nonveg_dry", "is_nonveg_gravy"]].apply(
            pd.to_numeric, errors="coerce").fillna(0)
        assert int(num["is_nonveg_dry"].sum()) >= COOLDOWN_FLOOR
        assert int(num["is_nonveg_gravy"].sum()) >= COOLDOWN_FLOOR


class TestThePoolsSurviveTheCooldown:
    """Why the list was seeded rather than built from Quest's 191 dishes: across
    eleven slots that is about seventeen each, and a `bread` row of one."""

    @pytest.mark.parametrize("course", [
        "bread", "rice", "dal", "veg_gravy", "veg_dry", "salad", "dessert",
        "starter", "nonveg_main",
    ])
    def test_a_daily_slot_has_dishes_to_rotate(self, hyd, course):
        assert len(_course(hyd, course)) >= COOLDOWN_FLOOR

    def test_a_standalone_quest_list_would_not_have(self):
        """The counterfactual, stated so the seeding decision is reviewable."""
        import scripts.import_quest_hyderabad_menu as imp
        printed = {v for vals in imp.parse().values() for v in vals}
        assert len(printed) < 250


class TestTheCorrectionChainRan:
    def test_colours_are_filled_where_the_evidence_allowed(self, hyd):
        """`item_color` drives the colour-variety rules and a blank is invisible
        to them — `_add_color_constraints` clamps the required distinct count to
        the colours PRESENT, so blanks quietly relax the rule."""
        coloured = hyd["item_color"].notna().sum()
        assert coloured / len(hyd) > 0.75

    def test_the_adjudicated_rows_came_with_the_seed(self):
        """Hyderabad carries Bangalore's rows, so it inherits the eight verdicts
        written about them. Mirrored rather than retyped — two copies of one
        verdict are two things that can disagree."""
        from scripts.audit_course_types import ADJUDICATED
        blr = {item for city, item in ADJUDICATED if city == "bangalore"}
        hyd = {item for city, item in ADJUDICATED if city == "hyderabad"}
        assert blr and blr == hyd

    def test_the_audit_is_clean(self, hyd):
        """No dish sits in a category belonging to something else. Run rather
        than trusted, because the audit is what stands between a menu import and
        a dessert served as a gravy."""
        from scripts.audit_course_types import audit_city
        unadjudicated, _allowed = audit_city(hyd, "hyderabad")
        assert not unadjudicated, unadjudicated


class TestTheImportIsIdempotent:
    def test_a_second_run_adds_nothing(self, tmp_path, monkeypatch):
        """The convention every correction script here follows. Run against a
        COPY so the committed workbook is never at risk."""
        import shutil
        import scripts.import_quest_hyderabad_menu as imp

        copy = tmp_path / "hyderabad.xlsx"
        shutil.copyfile(CITY_ITEMS_DIR / "hyderabad.xlsx", copy)
        monkeypatch.setattr(imp, "HYDERABAD", copy)
        monkeypatch.setattr(imp.SPEC, "city_path", copy)

        before = pd.read_excel(copy)
        imp.main()
        after = pd.read_excel(copy)
        assert len(after) == len(before)
        assert _names(after) == _names(before)
