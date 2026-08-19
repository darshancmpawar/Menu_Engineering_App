"""One dish, one spelling (`scripts/canonical_dish_spellings.py`).

The ontology wrote the same word two ways — `chana` 153 rows vs `channa` 16,
`sabzi` 77 vs `subzi` 13, `kadhi` 13 vs `kadi` 2 — and that is not cosmetic:

* a selector on the NAME misses half the family. `name_contains: ["kadhi"]` is
  the escape hatch the rule grammar offers when a column cannot be trusted, and
  it never saw `kadi_pakoda` or `sol_kadi`.
* a menu import stops being idempotent. `menu_import.SPELLING` rewrites an
  incoming `channa` to `chana`; while both spellings live in the workbook the
  fold reads the pair as two real words and keeps them apart, so the re-run adds
  a second row for a dish already present. Booking's import went 0 -> 9 new
  dishes on exactly this, and `kadai_subzi` did it again once Stripe's import
  put `subzi` into the vocabulary.

The tests below pin the fold, the two spellings deliberately left alone, and —
the part that matters most — that a rename which would merge two rows is
reported rather than applied.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd
import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from canonical_dish_spellings import (          # noqa: E402
    CANONICAL,
    DUPLICATES,
    KNOWN_SPLITS,
    apply,
    canonical_name,
)
from src.ontology.paths import city_excel_path  # noqa: E402

CITIES = ("bangalore", "pune", "chennai", "ncr")


def _frame(city):
    df = pd.read_excel(city_excel_path(city))
    df.columns = [c.strip() for c in df.columns]
    return df


@pytest.fixture(scope="module")
def frames():
    return {c: _frame(c) for c in CITIES}


def _rx(token):
    return re.compile(rf"(?<![a-z0-9]){token}(?![a-z0-9])")


# --------------------------------------------------------------------------
# The fold held
# --------------------------------------------------------------------------

@pytest.mark.parametrize("city", CITIES)
@pytest.mark.parametrize("minority", sorted(CANONICAL))
def test_no_minority_spelling_survives(frames, city, minority):
    rx = _rx(minority)
    stale = [n for n in frames[city]["item"].astype(str).str.strip().str.lower()
             if rx.search(n)]
    assert not stale, f"{city} still writes {minority!r}: {sorted(stale)[:8]}"


@pytest.mark.parametrize("city", CITIES)
@pytest.mark.parametrize("house", sorted(set(CANONICAL.values())))
def test_the_house_spelling_is_still_there(frames, city, house):
    """A fold that emptied the family would pass the test above vacuously.

    Only where the city HAS the family. The skip list used to name Chennai's
    three known gaps by hand and went stale the moment a city turned out to
    carry none of another family — Chennai has no handi, kolhapuri or laccha
    dish and Pune has no laccha, which is a fact about regional menus, not a
    fold that lost something. Deriving the precondition keeps the guard honest
    as the city lists grow.
    """
    names = frames[city]["item"].astype(str).str.strip().str.lower()
    minorities = [m for m, h in CANONICAL.items() if h == house]
    family = _rx(house)
    if not any(family.search(n) for n in names) and \
            not any(_rx(m).search(n) for m in minorities for n in names):
        pytest.skip(f"{city}'s list carries no {house} dish at all")
    assert any(family.search(n) for n in names)


def test_canonical_name_is_token_scoped():
    """`subz` must survive — it is a word, not a truncation of `subzi`."""
    assert canonical_name("subzi_pulao") == "sabzi_pulao"
    assert canonical_name("subz_makhani") == "subz_makhani"
    assert canonical_name("kadai_paneer") == "kadai_paneer"   # kadai != kadi
    assert canonical_name("kadi_pakoda") == "kadhi_pakoda"
    assert canonical_name("black_channa_masala") == "black_chana_masala"


def test_the_split_left_alone_is_still_split(frames):
    """`chapatti` / `chapati` is the client's call, and both are still there."""
    assert ("chapatti", "chapati") in KNOWN_SPLITS
    names = frames["bangalore"]["item"].astype(str).str.strip().str.lower()
    assert any(_rx("chapatti").search(n) for n in names)
    assert any(_rx("chapati").search(n) for n in names)


# --------------------------------------------------------------------------
# The merges, and the refusal to merge without a verdict
# --------------------------------------------------------------------------

@pytest.mark.parametrize("city", sorted(DUPLICATES))
def test_the_adjudicated_duplicates_are_gone(frames, city):
    """One row survives each adjudicated pair, under the house spelling.

    Asserting the dropped name is ABSENT was self-contradictory wherever the
    pair is `{already-canonical row: misspelled row}` — `chicken_kolhapuri`
    paired with `chicken_kolapuri` renames to `chicken_kolhapuri`, so the same
    string had to be both gone and present. What a merge actually promises is
    that the dish is there exactly once.
    """
    names = list(frames[city]["item"].astype(str).str.strip().str.lower())
    for dropped, kept in DUPLICATES[city].items():
        survivor = canonical_name(kept)
        assert survivor in names, f"{kept} was lost"
        assert names.count(survivor) == 1, f"{survivor} is duplicated"
        if canonical_name(dropped) != survivor:
            assert dropped not in names, f"{dropped} is back"


def test_a_merge_carries_the_dropped_rows_clients_over(frames):
    """Dropping the row without its clients silently removes a dish from them."""
    row = frames["ncr"][frames["ncr"]["item"].astype(str).str.strip().str.lower()
                        == "palak_kadhi"]
    assert len(row) == 1
    clients = {t.strip().lower()
               for t in str(row.iloc[0]["client"]).split(",") if t.strip()}
    # palak_kadhi carried Stryker; palak_kadi carried the other three
    assert {"stryker", "airtel noida", "siemens", "sinch"} <= clients, \
        sorted(clients)


def test_a_colliding_rename_is_reported_not_applied():
    """Two real dishes must never be merged by a spelling migration."""
    df = pd.DataFrame({"item": ["palak_kadi", "palak_kadhi"],
                       "client": ["A", "B"]})
    out, renamed, merged, collisions = apply(df, "no-such-city")
    assert renamed == [] and merged == []
    assert collisions == [("palak_kadi", "palak_kadhi")]
    assert len(out) == 2, "a collision must not drop a row"


@pytest.mark.parametrize("city", CITIES)
def test_rerunning_is_a_no_op(frames, city):
    out, renamed, merged, collisions = apply(frames[city], city)
    assert (renamed, merged, collisions) == ([], [], [])
    assert len(out) == len(frames[city])


@pytest.mark.parametrize("city", CITIES)
def test_names_and_ids_stay_unique(frames, city):
    assert frames[city]["item"].duplicated().sum() == 0
    assert frames[city]["item_id"].duplicated().sum() == 0


# --------------------------------------------------------------------------
# The payoff: the importers are stable again
# --------------------------------------------------------------------------

def test_a_name_selector_now_reaches_the_whole_kadhi_family(frames):
    """The reason the fold is worth doing at all."""
    for city in ("bangalore", "ncr"):
        names = frames[city]["item"].astype(str).str.strip().str.lower()
        hits = [n for n in names if "kadhi" in n]
        assert len(hits) >= 5, (city, sorted(hits))
        assert not [n for n in names if _rx("kadi").search(n)]
