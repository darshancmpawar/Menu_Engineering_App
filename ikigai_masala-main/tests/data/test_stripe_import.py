"""Stripe's two sample menus, imported into Bangalore
(`scripts/import_stripe_menu.py`).

The import reuses the shared three-pass machinery, so what this file pins is
what is specific to Stripe — the parts that were wrong on the first run and
would go wrong again silently:

* the **July workbook's salad-bar block is misaligned** (its dishes sit one row
  above their labels, so `Veg Soup` holds beverages). The parser detects that
  and re-pairs rather than assuming either layout, and a block it cannot line
  up is skipped rather than imported wrong.
* the **day-theme strip** ("Monday ( Rajasthan)", "Thursday-chinese") is not a
  row of dishes. Left in, its five strings imported as five salads, because the
  plated salad row directly beneath it carries no label of its own.
* only the **plated** meals are imported. The salad-bar components and the DIY
  sandwich station are things a diner assembles, not slots the solver fills.
* `protein_for` must read a protein word **anywhere** in the name. `\\b` does not
  fire next to `_`, so `tawa_fish_fry` matched nothing and fell through to the
  non-veg default — Stripe's fish was filed as chicken.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import import_stripe_menu as S                     # noqa: E402
from menu_import import protein_for, to_item       # noqa: E402
from src.ontology.paths import city_excel_path     # noqa: E402


def _norm(s):
    return str(s).strip().lower()


@pytest.fixture(scope="module")
def blr():
    df = pd.read_excel(city_excel_path("Bangalore"))
    df.columns = [c.strip() for c in df.columns]
    return df


@pytest.fixture(scope="module")
def imported(blr):
    """Every row Stripe is tagged on, not the rows tagged ONLY Stripe.

    Exact-match was the same thing when Stripe was the newest import; the
    Stryker, MOengage and Citrix imports then co-tagged the dishes they share
    with it, so `chapati` reads `Booking.com,Stripe,Stryker,MOengage` and every
    Stripe bread quietly left the set. Membership is what "the dishes this
    import contributed" means, and it is also the eligibility the pool filter
    computes.
    """
    token = S.CLIENT_TOKEN.lower()
    tagged = blr["client"].map(
        lambda cell: token in {t.strip().lower()
                               for t in str(cell).split(",") if t.strip()})
    return blr[tagged]


@pytest.fixture(scope="module")
def raw():
    return S.parse_source(verbose=False)


# --------------------------------------------------------------------------
# The parser: what it reads and what it refuses to
# --------------------------------------------------------------------------

def test_the_plated_salad_row_holds_salads_not_the_day_theme(raw):
    """The unlabelled row under the day strip is the salad; the strip is not."""
    salads = {to_item(d) for d in raw["Lunch||Salad"]}
    assert salads, "the plated lunch salad row was not read at all"
    assert not any(d.startswith(("monday", "tuesday", "wednesday", "thursday",
                                 "friday")) for d in salads), sorted(salads)
    assert "kachumber_salad" in salads


def test_the_misaligned_july_salad_bar_is_repaired_not_trusted(raw):
    """`Veg Soup` must hold soups and `Beverage` drinks, in BOTH workbooks.

    July's block lost a row, so by label its soups sit under "Menu Pattern" and
    its `Veg Soup` row holds juices. Importing by label would file five
    beverages as soups.
    """
    soups = {to_item(d) for d in raw["Salad Bar||Veg Soup"]}
    drinks = {to_item(d) for d in raw["Salad Bar||Beverage"]}
    # one from each workbook, so a silently-skipped file fails here
    assert {"tomato_soup", "dal_shorba_soup"} <= soups, sorted(soups)
    assert {"muskmelon_juice", "thandai"} <= drinks, sorted(drinks)
    assert not soups & drinks


def test_a_block_that_cannot_be_lined_up_is_skipped(monkeypatch):
    """The guard must fail closed — a wrong import is worse than a missing one."""
    monkeypatch.setattr(S, "ALIGNMENT_PROBE",
                        {"Veg Soup": ("nothing_matches_this",)})
    out = S.parse_source(verbose=False)
    assert "Salad Bar||Veg Soup" not in out
    # the plated blocks are unaffected — only the salad bar is probed
    assert out["Lunch||Gravy Veg"]


def test_the_salad_bar_components_and_sandwiches_are_not_imported(raw):
    for key in ("Salad Bar||Veg Protein (any 1)", "Salad Bar||Toppings ( any 4 )",
                "Salad Bar||Dressings ( any 4)", "Sandwich||Veg Sandwich",
                "Sandwich||Nonveg Sandwich"):
        assert key not in S.CATEGORY_MAP, f"{key} should not be imported"


def test_parenthesised_asides_are_dropped_from_dish_names():
    assert S.clean_name("Chicken tikka Masala(Boneless)") == "chicken_tikka_masala"
    assert S.clean_name("Mysore Rasam (Karnataka)") == "mysore_rasam"
    assert S.clean_name("Soya veg Cutlet(tasting)") == "soya_veg_cutlet"


# --------------------------------------------------------------------------
# protein_for: the boundary bug that filed fish as chicken
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name,course,expected", [
    ("tawa_fish_fry", "nonveg_main", "fish"),          # mid-name: the bug
    ("fish_finger", "nonveg_main", "fish"),
    ("singaporean_egg_fried_rice", "nonveg_main", "egg"),
    ("anda_keema_ghotala", "nonveg_main", "egg"),      # earliest match wins
    ("chicken_do_pyaza", "nonveg_main", "chicken"),
    ("mutton_curry", "nonveg_main", "mutton"),
    ("banjara_murgh_dry", "nonveg_main", "chicken"),   # no protein word -> default
    ("soya_keema_mutter", "veg_dry", ""),              # veg-qualified meat word
    ("keema_veg_biryani", "rice", ""),
    ("aloo_gobhi", "veg_gravy", ""),
])
def test_protein_for_reads_the_name(name, course, expected):
    assert protein_for(name, course) == expected


def test_stripes_fish_is_tagged_as_fish(blr):
    """Two dishes, both flagged — the seafood taxonomy depends on this."""
    fish = blr[blr["item"].map(_norm).isin({"tawa_fish_fry", "fish_finger"})]
    assert len(fish) == 2, sorted(fish["item"])
    assert (fish["primary_protein"].map(_norm) == "fish").all()
    for col in ("is_seafood", "is_fish_dish"):
        assert (fish[col].astype(int) == 1).all(), col


# --------------------------------------------------------------------------
# What landed in the ontology
# --------------------------------------------------------------------------

def test_the_import_added_dishes_across_the_plated_slots(imported):
    assert len(imported) > 50
    courses = set(imported["course_type"].map(_norm))
    assert {"bread", "rice", "veg_gravy", "veg_dry", "dal", "sambar",
            "nonveg_main", "dessert", "salad", "starter"} <= courses


def test_no_imported_dish_is_named_for_its_category(imported):
    """`remove_generic_rows.py` deletes these; an import must not add them back."""
    from remove_generic_rows import GENERIC_ROWS

    generic = {_norm(g) for g in GENERIC_ROWS}
    assert not (set(imported["item"].map(_norm)) & generic)


def test_names_and_ids_stay_unique(blr):
    assert blr["item"].duplicated().sum() == 0
    assert blr["item_id"].duplicated().sum() == 0


def test_every_imported_non_veg_dish_declares_a_protein(imported):
    nv = imported[imported["course_type"].map(_norm).isin({"nonveg_main",
                                                           "nonveg_soup"})]
    assert not nv.empty
    assert (nv["primary_protein"].map(_norm).str.len() > 0).all()


def test_no_imported_veg_dish_declares_a_protein(imported):
    """A protein in a veg slot makes `_nonveg_mask` drop the dish entirely."""
    veg = imported[~imported["course_type"].map(_norm).isin({"nonveg_main",
                                                             "nonveg_soup"})]
    stray = veg[veg["primary_protein"].map(_norm).isin(
        {"chicken", "mutton", "fish", "egg", "prawn", "lamb"})]
    assert stray.empty, sorted(stray["item"])


def test_rerunning_the_import_adds_nothing(blr):
    new_df, retag, _report, _log = S.build(blr.copy(),
                                           S.parse_source(verbose=False))
    assert len(new_df) == 0, sorted(new_df["item"])[:5]
    assert retag == 0


# --------------------------------------------------------------------------
# The data gaps this menu exposes, recorded rather than papered over
# --------------------------------------------------------------------------

def test_the_mutton_rule_is_wired_now_that_bangalore_has_mutton():
    """This started life as "Bangalore still has no mutton", a deliberate
    tripwire: Stripe's logic asks for mutton 2x/month and MOengage's for once a
    month, and while the city carried zero mutton dishes both rules would have
    been inert — so they were left unwritten with the test set to fail the
    moment that changed. A later client menu import added
    `dhaba_style_mutton_curry`, the tripwire fired, and the rules are now wired.

    So the guard flips: mutton exists, therefore the cadence rules must exist.
    """
    from src.menu_rules.menu_rule_loader import MenuRuleLoader

    for client, window in (("Stripe", 15), ("Moengage", 30)):
        rules = MenuRuleLoader().load_for_client(client, [])
        by_name = {r.name: r for r in rules}
        window_rule = next(
            (r for n, r in by_name.items() if "mutton" in n and "window" in n),
            None)
        assert window_rule is not None, f"{client} has no mutton window rule"
        assert window_rule.validate_config(), window_rule.validation_errors()
        assert window_rule.config.get("window_days") == window, client
        assert any("mutton" in n and n.endswith("max_1") for n in by_name), \
            f"{client} has no within-plan mutton cap"


def test_the_mutton_pool_is_a_single_dish(blr):
    """Which is why both rules are caps rather than positive cadences: a target
    would force the same one dish on a schedule regardless of the plate."""
    mutton = blr[blr["primary_protein"].map(_norm) == "mutton"]
    assert list(mutton["item"]) == ["dhaba_style_mutton_curry"], \
        sorted(mutton["item"])
    assert (mutton["course_type"].map(_norm) == "nonveg_main").all()


def test_the_fish_pool_is_thin_enough_to_matter(blr):
    """Two dishes cannot carry a weekly fish rule under the 20-day cooldown."""
    fish = blr[blr["is_fish_dish"].astype(int) == 1]
    assert len(fish) < 5, (
        "Bangalore's fish pool grew — a weekly fish cadence may now be "
        f"servable: {sorted(fish['item'])}")
