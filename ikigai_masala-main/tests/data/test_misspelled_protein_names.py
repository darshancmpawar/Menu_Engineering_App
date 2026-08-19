"""Meat-named dishes sitting in veg pools (`scripts/misspelled_protein_names.py`).

Four rows across Bangalore and NCR were named for chicken or mutton while every
attribute said vegetarian, so the solver served them from the veg `starter`,
`rice` and `veg_gravy` pools and the menu printed a meat name to a vegetarian.

The misspelling is what hid them: `audit_course_types.py` matches whole
`_`-tokens of a dish name against real dish words, and "chciken"/"chivken"/
"muton" are not words, so no name-based check could see any of them. The
importer's fold was blinded the same way — with `chciken` in the vocabulary as a
"real" token, `chciken_mulligatawny` and `chicken_mulligatawny` read as two
dishes rather than one misspelling, which is the assertion that first failed.

Pinned here:

* each of the four corrections stays applied, and re-running the script is a
  no-op;
* the dishes kept are still correct (the veg biryani reads veg, the re-filed
  mutton reads non-veg and reaches only the non-veg pool);
* **generally**, no dish name in ANY city contains a misspelled protein word —
  the guard the four fixes are instances of.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from misspelled_protein_names import (            # noqa: E402
    PROTEIN_TYPO_RE,
    REFILE,
    REMOVE,
    RENAME,
    apply,
)
from src.constants import NONVEG_PROTEINS, NONVEG_SLOTS   # noqa: E402
from src.ontology.paths import city_excel_path            # noqa: E402

CITIES = ("Bangalore", "Pune", "Chennai", "NCR")


def _frame(city):
    df = pd.read_excel(city_excel_path(city))
    df.columns = [c.strip() for c in df.columns]
    return df


@pytest.fixture(scope="module")
def frames():
    return {c.lower(): _frame(c) for c in CITIES}


def _names(df):
    return set(df["item"].astype(str).str.strip().str.lower())


def _row(df, name):
    hit = df[df["item"].astype(str).str.strip().str.lower() == name]
    assert len(hit) == 1, f"expected exactly one {name}, found {len(hit)}"
    return hit.iloc[0]


# --------------------------------------------------------------------------
# The four specific corrections
# --------------------------------------------------------------------------

@pytest.mark.parametrize("city", ["bangalore", "ncr"])
def test_the_misspelled_names_are_gone(frames, city):
    names = _names(frames[city])
    stale = (set(RENAME.get(city, {})) | set(REMOVE.get(city, {}))
             | set(REFILE.get(city, {})))
    assert not (stale & names), f"{city} still carries {sorted(stale & names)}"


def test_the_renamed_biryani_survives_and_still_reads_as_veg(frames):
    """It is a real dish two clients serve — the NAME was the only thing wrong."""
    r = _row(frames["bangalore"], "hoskote_veg_biryani")
    assert str(r["course_type"]).strip().lower() == "rice"
    assert str(r.get("primary_protein") or "").strip().lower() in ("", "nan")
    assert int(r["is_mixedveg_biryani"]) == 1
    assert str(r["sub_category"]).strip().lower() == "north_veg_biryani"


def test_the_refiled_mutton_reads_as_non_veg(frames):
    """NCR's only mutton: removing it would drop the dish Siemens asks for, so
    it is re-filed with the attributes its NAME supports."""
    r = _row(frames["ncr"], "mutton_curry")
    assert str(r["course_type"]).strip().lower() in NONVEG_SLOTS
    assert str(r["primary_protein"]).strip().lower() == "mutton"
    assert str(r["primary_protein"]).strip().lower() in NONVEG_PROTEINS
    # a veg template flag left behind would put a mutton curry back in a veg pool
    assert int(r["is_mixedveg_gravy"]) == 0


def test_the_refiled_mutton_reaches_only_the_non_veg_pool(frames):
    """`_nonveg_mask` confines it — the point of giving it a real protein."""
    from src.preprocessor.pool_builder import PoolBuilder

    pools = PoolBuilder().build_pools(frames["ncr"], required_slots=set())
    found = {slot for slot, pool in pools.items()
             if "mutton_curry" in set(pool["item"].astype(str).str.strip()
                                      .str.lower())}
    assert found, "mutton_curry reaches no pool at all"
    assert all(s.split("__")[0] in NONVEG_SLOTS for s in found), sorted(found)


def test_the_removed_rows_left_their_proper_twins_alone(frames):
    """Each removal was a duplicate — the properly-filed dish must remain."""
    r = _row(frames["bangalore"], "chicken_kebab")
    assert str(r["primary_protein"]).strip().lower() == "chicken"
    assert str(r["course_type"]).strip().lower() == "nonveg_main"
    for twin in ("hyderabadi_chicken_curry", "hyderabadi_chicken_masala"):
        assert str(_row(frames["ncr"], twin)["primary_protein"]).strip().lower() \
            == "chicken"


def test_no_pool_is_starved_by_the_removals(frames):
    ct = frames["bangalore"]["course_type"].astype(str).str.strip().str.lower()
    assert int(ct.eq("starter").sum()) > 100
    ct = frames["ncr"]["course_type"].astype(str).str.strip().str.lower()
    assert int(ct.eq("nonveg_main").sum()) > 20


@pytest.mark.parametrize("city", ["bangalore", "pune", "chennai", "ncr"])
def test_names_and_ids_stay_unique(frames, city):
    df = frames[city]
    assert df["item"].duplicated().sum() == 0
    assert df["item_id"].duplicated().sum() == 0


@pytest.mark.parametrize("city", ["bangalore", "ncr"])
def test_rerunning_is_a_no_op(frames, city):
    out, renamed, removed, refiled = apply(frames[city], city)
    assert (renamed, removed, refiled) == ([], [], [])
    assert len(out) == len(frames[city])


# --------------------------------------------------------------------------
# The general guard the four fixes are instances of
# --------------------------------------------------------------------------

@pytest.mark.parametrize("city", CITIES)
def test_no_city_carries_a_misspelled_protein_word(city):
    """A misspelled protein hides a row from every name-based audit.

    Deliberately scoped to protein words rather than every entry in
    `menu_import.SPELLING`: most of those correct a regional transliteration
    (`kozambu` -> `kuzhambu`) where both spellings read fine on a menu, and some
    map a word to itself. A misspelled *protein* is different in kind — it is
    the one typo that lets a meat dish pass as vegetarian.
    """
    df = _frame(city)
    offenders = [n for n in df["item"].astype(str).str.strip().str.lower()
                 if PROTEIN_TYPO_RE.search(n)]
    assert not offenders, f"{city} carries meat-name typos: {sorted(offenders)}"


@pytest.mark.parametrize("city", CITIES)
def test_no_meat_named_dish_sits_in_a_veg_pool(city):
    """The defect itself, stated directly and checked pan-India.

    A dish whose name declares an animal protein must declare that protein on
    the row too — otherwise `_nonveg_mask` leaves it in the veg pools and a
    vegetarian is served it. Veg dishes that borrow a meat word for a meat-free
    version (`veg_seekh_kabab`, `soya_keema`, `keema_veg_biryani`,
    `red_velvet_pastry_egg_less`) say so in the same name, so they are exempt.
    """
    df = _frame(city)
    veg_qualifiers = ("veg", "soya", "soyabean", "mushroom", "less", "paneer")
    offenders = []
    for _, r in df.iterrows():
        name = str(r["item"]).strip().lower()
        toks = set(name.split("_"))
        meat = toks & NONVEG_PROTEINS
        if not meat or toks & set(veg_qualifiers):
            continue
        protein = str(r.get("primary_protein") or "").strip().lower()
        if protein and protein != "nan":
            continue
        offenders.append((name, str(r["course_type"]).strip().lower()))
    assert not offenders, (
        f"{city}: meat-named dishes with no protein declared — they sit in the "
        f"veg pools: {sorted(offenders)}")
