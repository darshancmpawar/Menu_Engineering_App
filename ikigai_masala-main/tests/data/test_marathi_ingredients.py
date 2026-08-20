"""The Marathi vegetable names, given a `key_ingredient` the rules can select on.

`complete_ontology.py` correctly refused these: a token vote can only propose a
value the ontology already uses for dishes with that word in the name, and until
Corning Chakan's menu arrived no row had ever carried `dodka`, `shepu` or
`matki`. A dictionary can settle what a data vote cannot — `dodka` IS ridge
gourd — and that is what this script is.

The risk it carries is inventing vocabulary. `key_ingredient` is read by
`attribute_grouping` (the sambar and dal slots group by it), `ingredient_ban_rule`
and `selector_frequency`; a value no rule names is as invisible as a blank. So
these tests pin that the values are the ontology's own.
"""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.marathi_ingredient_names import (
    CITIES,
    CITY_DIR,
    LENTILS,
    LENTIL_COURSES,
    PHRASES,
    RENAME,
    VEGETABLES,
    apply,
    propose,
)


def _read(city):
    df = pd.read_excel(CITY_DIR / f"{city}.xlsx")
    df.columns = [c.strip() for c in df.columns]
    return df


@pytest.fixture(scope="module")
def frames():
    return {c: _read(c) for c in CITIES}


@pytest.fixture(scope="module")
def vocabulary(frames):
    everything = pd.concat(frames.values(), ignore_index=True)
    return set(everything["key_ingredient"].dropna().astype(str)
               .str.strip().str.lower())


class TestTheValuesAreTheOntologysOwn:

    def test_almost_every_value_already_existed(self, vocabulary):
        """A new synonym for an ingredient the ontology already names would be
        invisible to the rules that name the old one — which is the bug
        `protein_key_ingredients.py` exists to fix."""
        emitted = set(VEGETABLES.values()) | set(LENTILS.values()) \
            | set(PHRASES.values())
        introduced = sorted(v for v in emitted if v not in vocabulary)
        assert not introduced, introduced

    def test_the_short_form_won_where_the_ontology_uses_it(self):
        """`moth` not `moth_bean`, `yam` not `elephant_yam`, `leafy_greens` not
        `mustard_greens` — the ontology's spelling, not the dictionary's."""
        assert LENTILS["amti"] == "toor_dal"
        assert VEGETABLES["matki"] == "moth"
        assert VEGETABLES["suran"] == "yam"
        assert VEGETABLES["sarso"] == "leafy_greens"

    def test_kala_chana_uses_the_on_list_value(self, vocabulary):
        """It has to be a value the client's protein list names, or
        `protein_source_daily` stops seeing the dish."""
        from scripts.protein_key_ingredients import PROTEIN_KEY_INGREDIENTS
        assert PHRASES[("kala", "chana")] == "chickpea"
        assert "chickpea" in PROTEIN_KEY_INGREDIENTS


class TestTheSplitLentilIsNotTheWholeLegume:

    def test_chana_dal_beats_a_bare_chana(self):
        """Matching one token at a time filed `chana_chaat_salad` and
        `kabuli_chana_chaat` as `chana_dal`, which is split gram — a chana chaat
        is made of the whole chickpea."""
        assert propose("chana_dal_fry", "dal")[0] == "chana_dal"
        assert propose("kabuli_chana_chaat", "salad")[0] == "chickpea"
        assert propose("chana_chaat_salad", "salad")[0] == "chickpea"

    def test_the_phrase_tables_win_over_single_words(self):
        assert propose("hara_moong_dal_with_raw_mango", "dal")[0] == "moong_dal"
        assert propose("green_moong_sundal", "salad")[0] == "green_moong"


class TestTheCoursePicksWhichTableLeads:

    def test_a_dal_is_keyed_by_its_lentil(self):
        assert propose("dal_waran", "dal")[0] == "toor_dal"
        for course in LENTIL_COURSES:
            assert propose("amti", course)[0] == "toor_dal"

    def test_a_vegetable_dish_is_keyed_by_its_vegetable(self):
        """`shepu_moongdal` is a dill dry veg; the lentil is the binder."""
        assert propose("shepu_moongdal", "veg_dry")[0] == "dill"
        assert propose("dodka_moongdal", "veg_dry")[0] == "ridge_gourd"


class TestWhatItActuallyFilled:

    def test_the_marathi_dishes_carry_an_ingredient_now(self, frames):
        by_item = dict(zip(frames["pune"]["item"].astype(str).str.lower(),
                           frames["pune"]["key_ingredient"].astype(str)
                           .str.strip().str.lower()))
        for dish, want in (("dodka_masala", "ridge_gourd"),
                           ("shepu_tomato", "dill"),
                           ("gawar_masala", "cluster_beans"),
                           ("matki_masala", "moth"),
                           ("bharali_wangi", "eggplant"),
                           ("chavali_sheng_dry", "black_eyed_pea"),
                           ("amti", "toor_dal"),
                           ("patodi", "besan")):
            assert by_item.get(dish) == want, (dish, by_item.get(dish))

    def test_one_ingredient_one_spelling(self, frames):
        """`flaxiseed` sat on a single row beside the `flaxseed` this writes."""
        for city, df in frames.items():
            values = set(df["key_ingredient"].dropna().astype(str)
                         .str.strip().str.lower())
            for old in RENAME:
                assert old not in values, (city, old)

    def test_it_never_overwrites_a_value_already_there(self, frames):
        """Fills blanks only, apart from the explicit RENAME."""
        df = frames["pune"]
        out, _filled = apply(df)
        had = df["key_ingredient"].notna() & ~df["key_ingredient"].astype(str) \
            .str.strip().str.lower().isin(RENAME)
        assert (out.loc[had, "key_ingredient"].astype(str)
                == df.loc[had, "key_ingredient"].astype(str)).all()


class TestRunningItAgainChangesNothing:

    @pytest.mark.parametrize("city", CITIES)
    def test_a_second_pass_fills_nothing(self, frames, city):
        _out, filled = apply(frames[city])
        assert not filled, filled[:5]
