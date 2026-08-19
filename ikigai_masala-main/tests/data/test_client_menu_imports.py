"""The Stryker, MOengage and Citrix menu imports.

Three Bangalore sites, three quite different printed layouts, one shared
machinery (`scripts/menu_import.py`). What is pinned here is what each source
does that a plain grid reader gets wrong — every one of these was a real bug
during the import, and every one is silent: the dish lands somewhere plausible
and nobody notices until a menu prints it.

* **Stryker** — a "Combo Spot" block that repackages the same week's buffet
  (no new dishes, and unlabelled rows that inherit the wrong label); a
  nutrition block whose `allergen` column imported "gluten"/"dairy"/"soya" as
  dishes; and two sheets carrying a SECOND grid with its own label column, one
  beside the first and one stacked below it. A single global column
  segmentation handled the side-by-side case and got the stacked one wrong.
* **MOengage** — "Na"/"-" mean the category is not served that day; "Puri +
  Chapti" is two dishes; the flavoured rice sits on an unlabelled row beneath
  the steamed-rice one.
* **Citrix** — a portion-size column between every pair of day columns (they
  hold "Adq", not only numbers); `Welcome Drink/Soup` is one row for two slots;
  and NI/SI cuisine markers hang off the dish names.

Plus the invariants that apply to every import: idempotence, no category names
as dishes, no meat-named dish in a veg pool, and one dish in one category.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import import_citrix_menu as CITRIX          # noqa: E402
import import_moengage_menu as MOENGAGE      # noqa: E402
import import_stryker_menu as STRYKER        # noqa: E402
from menu_import import (                    # noqa: E402
    is_placeholder,
    refile_lentils,
    refile_rice,
    split_combo,
    to_item,
)
from src.constants import NONVEG_PROTEINS, NONVEG_SLOTS   # noqa: E402
from src.ontology.paths import city_excel_path            # noqa: E402

MODULES = {"Stryker": STRYKER, "MOengage": MOENGAGE, "Citrix": CITRIX}


def _norm(s):
    return str(s).strip().lower()


@pytest.fixture(scope="module")
def blr():
    df = pd.read_excel(city_excel_path("Bangalore"))
    df.columns = [c.strip() for c in df.columns]
    return df


@pytest.fixture(scope="module")
def raws():
    return {name: mod.parse_source() for name, mod in MODULES.items()}


# --------------------------------------------------------------------------
# Each source's own trap
# --------------------------------------------------------------------------

def test_strykers_combo_block_is_not_imported(raws):
    """It re-serves the same week's buffet; its rows carry no label of their own."""
    labels = {k.split("||", 1)[1] for k in raws["Stryker"]}
    assert not any("combo" in lab for lab in labels), sorted(labels)
    assert "veg combo" not in labels


def test_strykers_allergen_column_is_not_read_as_dishes(raws):
    """One sheet interleaves kcal/protein/fat/carb/fiber/allergen columns."""
    dishes = {to_item(d) for v in raws["Stryker"].values() for d in v}
    assert not dishes & {"gluten", "dairy", "daiyr", "nuts", "soya",
                         "gluten_dairy", "daiyr_nuts"}


def test_strykers_second_grid_files_dishes_under_its_own_labels(raws):
    """Two sheets carry a second grid — one beside the first, one stacked below.

    Segmenting the sheet by column alone got the stacked case wrong and put an
    Amritsari veg dry into `rasam`; reading that grid's label column as dishes
    added "Indian Bread" and "Spl item" as menu items.
    """
    raw = raws["Stryker"]
    veg_dry = {to_item(d) for d in raw.get("Lunch||veg dry", [])}
    rasam = {to_item(d) for d in raw.get("Lunch||rasam", [])}
    assert "amritsari_mix_veg_dry" in veg_dry
    assert "amritsari_mix_veg_dry" not in rasam
    every = {to_item(d) for v in raw.values() for d in v}
    assert not every & {"indian_bread", "spl_item", "flavour_rice", "veg_gravy",
                        "non_veg", "papapd"}


def test_strykers_live_counter_prefix_is_the_station_not_the_dish():
    assert STRYKER.clean_name("Live Counter- Jhal Muri") == "jhal_muri"
    assert STRYKER.clean_name("Veg Cutlet /Green Chutney") == "veg_cutlet"
    assert STRYKER.clean_name("Mix Veg Cutlet with Green Chutney") \
        == "mix_veg_cutlet"


def test_a_with_name_is_only_trimmed_when_it_is_spelled_with():
    """"X with Y" is the ontology's OWN convention, not noise to strip.

    Over a hundred rows are named that way — `malpua_with_rabri`,
    `pesarattu_with_ginger_chutney`, `curd_rice_with_tadka` — and most predate
    any import. Stryker's grid uses the same phrasing for "served with", so its
    reader trims it; one source cell spells it "wih", which the trim does not
    match, and that is deliberately left alone. Fixing the typo now would
    rename a dish already in the workbook and the import would stop being
    idempotent, for a name that reads fine beside
    `crispy_baby_corn_with_hot_garlic_sauce` anyway.
    """
    assert STRYKER.clean_name("Babycorn Dry wih Manchurain Gravy Sauce") \
        == "babycorn_dry_with_manchurian_gravy_sauce"


def test_moengage_placeholders_are_not_dishes(raws):
    """"Na", "-" and "--" mean the category is not served that day."""
    for text in ("Na", "-", "--", "  ", "Holiday"):
        assert is_placeholder(text), text
    dishes = {to_item(d) for v in raws["MOengage"].values() for d in v
              if not is_placeholder(d)}
    assert not dishes & {"na", "nil", "none", "holiday"}


def test_combo_cells_split_into_separate_dishes():
    assert split_combo("Puri + Chapti") == ["Puri", "Chapti"]
    assert split_combo("Idli + Chutney") == ["Idli", "Chutney"]
    # `and` and `&` appear INSIDE dish names and must not split
    assert split_combo("Salt & Pepper Corn") == ["Salt & Pepper Corn"]
    assert split_combo("Aloo Gobhi and Methi") == ["Aloo Gobhi and Methi"]


def test_moengage_flavoured_rice_row_is_read(raws):
    """It has no label of its own — it continues the steamed-rice row above."""
    rice = {to_item(d) for d in raws["MOengage"].get("Lunch||rice", [])}
    assert len(rice) > 20, sorted(rice)[:10]
    assert "veg_donne_biryani" in rice or "navratan_pulao" in rice


def test_citrix_quantity_columns_are_not_read_as_dishes(raws):
    """The `Kg/Pcs` columns hold "Adq" as well as numbers."""
    dishes = {to_item(d) for v in raws["Citrix"].values() for d in v}
    assert "adq" not in dishes


def test_citrix_welcome_drink_soup_row_splits_by_name():
    """One printed row, two solver slots."""
    assert CITRIX.refile("roasted_tomato_soup", "welcome_drink") == "soup"
    assert CITRIX.refile("masala_buttermilk", "welcome_drink") == "welcome_drink"
    assert CITRIX.refile("dhaniya_shorba", "welcome_drink") == "soup"


def test_citrix_cuisine_markers_are_stripped_from_names():
    """"Udupi Veg Kurma SI" is the dish the ontology already calls udupi_veg_kurma."""
    assert CITRIX.clean_name("Udupi Veg Kurma SI") == "udupi_veg_kurma"
    assert CITRIX.clean_name("Carrot methi subzi NI") == "carrot_methi_sabzi"
    assert CITRIX.clean_name("Veg Hyderabadi gravy N") == "veg_hyderabadi_gravy"


# --------------------------------------------------------------------------
# The shared name-based re-filing
# --------------------------------------------------------------------------

@pytest.mark.parametrize("item,course,expected", [
    # a printed grid puts what the day needs in whatever row has space
    ("millets_khichdi", "dal", "rice"),
    ("red_rice_pilaf", "dal", "rice"),
    ("veg_kofta_biryani", "curd_side", "rice"),
    # already home
    ("chicken_biryani", "nonveg_main", "nonveg_main"),
    ("veg_pulao", "rice", "rice"),
    ("millet_khichdi", "healthy_rice", "healthy_rice"),
    # NOT rice: a sweet named for a rice dish, and the curd-rice station
    ("kesari_bath", "dessert", "dessert"),
    ("curd_rice", "curd_rice", "curd_rice"),
])
def test_a_rice_is_a_rice_whatever_row_it_was_printed_on(item, course, expected):
    assert refile_rice(item, course) == expected


@pytest.mark.parametrize("item,expected", [
    ("mix_veg_sambar", "sambar"),
    ("tomato_rasam", "rasam"),
    ("dal_tadka", "dal"),
    ("millets_khichdi", "rice"),          # the rice rule runs first
])
def test_the_lentil_family_is_filed_by_name(item, expected):
    assert refile_lentils(item, "dal") == expected


# --------------------------------------------------------------------------
# Invariants every import has to hold
# --------------------------------------------------------------------------

@pytest.mark.parametrize("client", sorted(MODULES))
def test_rerunning_the_import_adds_nothing(blr, client):
    mod = MODULES[client]
    new_df, retag, _report, _log = mod.build(blr.copy(), mod.parse_source())
    assert len(new_df) == 0, sorted(new_df["item"])[:6]
    assert retag == 0


@pytest.mark.parametrize("client", sorted(MODULES))
def test_the_import_actually_landed(blr, client):
    mine = blr[blr["client"].map(_norm).str.contains(client.lower(), na=False)]
    assert len(mine) > 40, f"{client} contributed almost nothing"


@pytest.mark.parametrize("client", sorted(MODULES))
def test_no_imported_dish_is_named_for_its_category(blr, client):
    from menu_import import generic_row_names

    mine = blr[blr["client"].map(_norm).str.contains(client.lower(), na=False)]
    assert not set(mine["item"].map(_norm)) & generic_row_names()


def test_the_generic_guard_is_not_vacuous():
    """`GENERIC_ROWS` is a city -> names mapping; iterating it directly matched
    dish names against {'chennai', 'ncr', 'pune'} and caught nothing."""
    from menu_import import generic_row_names

    names = generic_row_names()
    assert {"salad", "sweet", "veg_dry", "rasam"} <= names
    assert not names & {"chennai", "ncr", "pune"}


@pytest.mark.parametrize("client", sorted(MODULES))
def test_no_imported_meat_dish_sits_in_a_veg_pool(blr, client):
    """`_nonveg_mask` would drop it from that pool and it becomes unservable."""
    mine = blr[blr["client"].map(_norm).str.contains(client.lower(), na=False)]
    veg = mine[~mine["course_type"].map(_norm).isin(NONVEG_SLOTS)]
    stray = veg[veg["primary_protein"].map(_norm).isin(NONVEG_PROTEINS)]
    assert stray.empty, sorted(stray["item"])


def test_every_imported_non_veg_dish_declares_a_protein(blr):
    imported = blr[blr["client"].map(_norm).str.contains(
        "stryker|moengage|citrix", na=False, regex=True)]
    nv = imported[imported["course_type"].map(_norm).isin(NONVEG_SLOTS)]
    assert not nv.empty
    assert (nv["primary_protein"].map(_norm).str.len() > 0).all()


def test_names_and_ids_stay_unique(blr):
    assert blr["item"].duplicated().sum() == 0
    assert blr["item_id"].duplicated().sum() == 0


def test_one_dish_lands_in_exactly_one_category(blr):
    """`COURSE_PRIORITY` exists so a dish printed in two rows is filed once."""
    counts = blr.groupby(blr["item"].map(_norm))["course_type"].nunique()
    assert counts.max() == 1, sorted(counts[counts > 1].index)[:8]
