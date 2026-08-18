"""Booking.com's 3-month menu, imported into Bangalore
(`scripts/import_booking_menu.py`).

The client asked for the menu to be added the way earlier imports were: unique
items only, similar items folded, and the spelling normalised. Two categories
came out of it that the app did not have — `infused_water` (its Detox water row)
and `nonveg_soup` (its Non Veg Soup row).

These pin the parts that are easy to break silently:

* the fold must not merge dishes that merely LOOK alike (`greek_salad` /
  `green_salad`, `kadai_paneer` / `kadhi_paneer` — the same mistake
  `ncr_fuzzy_unmerge.py` had to reverse), and must keep the better-spelled name
  when it does merge;
* a non-veg soup has to survive in its own slot, since non-veg dishes are
  dropped from every slot that is not a non-veg one;
* `infused_water` must not fall back into the welcome-drink pool;
* the import must be idempotent, like every other correction script.
"""

from __future__ import annotations

import re

import pandas as pd
import pytest

from scripts.import_booking_menu import (
    CLIENT_TOKEN,
    COMMON_AT,
    KEEP_APART,
    _existing_twin,
    fold_similar,
    to_item,
    vocab_from,
)
from src.ontology.paths import city_excel_path

NEW_CATEGORIES = ("infused_water", "nonveg_soup")


def _norm(s):
    return str(s).strip().lower()


@pytest.fixture(scope="module")
def blr():
    df = pd.read_excel(city_excel_path("Bangalore"))
    df.columns = [c.strip() for c in df.columns]
    return df


@pytest.fixture(scope="module")
def imported(blr):
    return blr[blr["client"].map(_norm) == CLIENT_TOKEN.lower()]


# --------------------------------------------------------------------------
# The two new categories
# --------------------------------------------------------------------------

def test_both_new_categories_have_dishes(blr):
    ct = blr["course_type"].map(_norm)
    for cat in NEW_CATEGORIES:
        assert int(ct.eq(cat).sum()) > 20, f"{cat} is too thin to serve daily"


def test_every_non_veg_soup_declares_a_protein(blr):
    """Otherwise it is a veg dish sitting in a non-veg slot."""
    rows = blr[blr["course_type"].map(_norm) == "nonveg_soup"]
    assert not rows.empty
    assert (rows["primary_protein"].map(_norm).str.len() > 0).all()


def test_a_non_veg_soup_reaches_its_own_pool(blr):
    """`_nonveg_mask` drops non-veg dishes from every slot but the non-veg ones.

    A bare `slot == 'nonveg_main'` check emptied this whole category, which is
    why `NONVEG_SLOTS` is a set.
    """
    from src.preprocessor.pool_builder import PoolBuilder
    pools = PoolBuilder.build_pools(blr)
    assert len(pools["nonveg_soup"]) > 20
    veg_slots = set(pools) - {"nonveg_main", "nonveg_soup"}
    soups = set(pools["nonveg_soup"]["item"].map(_norm))
    for slot in veg_slots:
        assert not (soups & set(pools[slot]["item"].map(_norm))), slot


def test_infused_water_is_not_absorbed_by_welcome_drink(blr):
    from src.preprocessor.pool_builder import PoolBuilder
    pools = PoolBuilder.build_pools(blr)
    infused = set(pools["infused_water"]["item"].map(_norm))
    drinks = set(pools["welcome_drink"]["item"].map(_norm))
    assert len(infused) > 20
    assert not (infused & drinks)


def test_the_new_slots_are_off_by_default():
    """They came from one client's menu; switching them on for the other 50
    Bangalore counters would change every one of their plans."""
    from src.constants import BASE_SLOT_NAMES, DEFAULT_OFF_SLOTS
    for cat in NEW_CATEGORIES:
        assert cat in BASE_SLOT_NAMES
        assert cat in DEFAULT_OFF_SLOTS


# --------------------------------------------------------------------------
# The fold — what it must and must not merge
# --------------------------------------------------------------------------

def test_dishes_that_only_look_alike_are_kept_apart(blr):
    """`kadai` is the wok, `kadhi` the yogurt curry; `greek` is not `green`."""
    names = set(blr["item"].map(_norm))
    vocab = vocab_from(blr)
    for a, b in KEEP_APART:
        pair = sorted(n for n in names if a in n.split("_") or b in n.split("_"))
        assert pair, f"neither {a} nor {b} survives in the ontology"
    # and the fold itself refuses to merge them
    kept = fold_similar({"greek_salad", "green_salad"}, vocab=vocab)
    assert set(kept) == {"greek_salad", "green_salad"}


def test_the_fold_keeps_the_better_spelling(blr):
    """Sorting alphabetically kept `chciken_...` over `chicken_...`; these names
    get printed on a menu, so that is not cosmetic."""
    vocab = vocab_from(blr)
    kept = fold_similar({"chciken_mulligatawny", "chicken_mulligatawny"},
                        vocab=vocab)
    assert kept == ["chicken_mulligatawny"]


def test_no_imported_name_carries_a_known_misspelling(imported):
    """The corrections are applied on snake_case tokens.

    They were originally written with `\\b`, which never fires next to `_`
    because an underscore is a word character — so every one of them was
    silently inert on multi-word names.
    """
    bad = {"chciken", "chcken", "chiceken", "parataha", "biriyani", "idly",
           "pomogranate", "kanjee", "corriander", "mediteranean", "tortila",
           "minstrone", "muligatawany", "vanila", "pinepple", "cury"}
    for name in imported["item"].map(_norm):
        tokens = set(re.split(r"[^a-z0-9]+", name))
        assert not (tokens & bad), f"{name} still carries a misspelling"


def test_a_serving_style_word_folds_into_the_base_dish(blr):
    """`plain_chapati` beside `chapati` is one dish twice."""
    vocab = vocab_from(blr)
    assert _existing_twin("plain_dosa", ["dosa", "masala_dosa"], vocab) == "dosa"
    # ...but `veg` changes what the dish IS, so it must not fold
    assert _existing_twin("veg_biryani", ["biryani"], vocab) != "biryani"


def test_to_item_strips_printed_menu_numbering():
    assert to_item("1. Enchilladas with Salsa").startswith("enchilada")
    assert not to_item("2) Veg Pulao").startswith("2")


# --------------------------------------------------------------------------
# Client tagging and idempotence
# --------------------------------------------------------------------------

def test_imported_dishes_are_tagged_to_booking(imported):
    assert len(imported) > 400
    assert set(imported["client"].map(_norm)) == {CLIENT_TOKEN.lower()}


def test_no_row_lists_more_clients_than_the_common_threshold(blr):
    """The client's rule: 6+ clients making a dish means it is `common`."""
    for value in blr["client"].dropna().astype(str):
        tokens = [t for t in value.split(",") if t.strip()]
        if len(tokens) >= COMMON_AT:
            assert any(t.strip().lower() == "common" for t in tokens), value


def test_ids_and_names_stay_unique(blr):
    assert blr["item"].duplicated().sum() == 0
    assert blr["item_id"].duplicated().sum() == 0


def test_rerunning_the_import_adds_nothing(blr):
    """The fold reads the ontology's vocabulary, so a naive re-run split pairs
    it had merged and added 14 dishes. The vocabulary excludes this import's own
    rows for exactly that reason."""
    from scripts.import_booking_menu import build, parse_source
    new_df, retag, _report, _log = build(blr.copy(), parse_source())
    assert len(new_df) == 0, sorted(new_df["item"])[:5]
    assert retag == 0
