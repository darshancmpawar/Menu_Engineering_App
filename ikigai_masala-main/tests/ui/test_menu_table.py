"""`day_cells` — the plan-block → component-arguments shaping.

The component itself is HTML and JS and is not tested here. What is tested is
the boundary between them, because every field below is one the table reads
positionally: get `cells` keyed by the wrong string and the row renders empty
with no error, which looks exactly like a day the solver could not fill.

The cell key is `"<slot_id>|<iso>"`, and it is the SAME string the component
sends back in a regenerate request. One spelling, asserted here, or the two
halves drift and a planner's selection silently regenerates nothing.
"""

from __future__ import annotations

from ui.menu_table import _color_key, day_cells

DATES = ["2026-09-21", "2026-09-22"]
PLAN = {
    "2026-09-21": {"rice": "veg_fried_rice(Y)", "nonveg_main": "chicken_curry(R)"},
    "2026-09-22": {"rice": "jeera_rice(W)", "nonveg_main": "egg_masala(O)"},
}
THEMES = {"2026-09-21": "mix", "2026-09-22": "chinese"}


def _args(**kw):
    return day_cells(PLAN, DATES, THEMES, **kw)


def test_the_colour_suffix_is_read_and_removed_from_the_name():
    """`veg_fried_rice(Y)` is a yellow dish called Veg Fried Rice. The suffix
    drives the cell's colour dot and must not also print in the name."""
    cell = _args()["rows"][0]["cells"]["2026-09-21"]
    assert cell["color"] == "Y"
    assert cell["name"] == "Veg Fried Rice"
    assert "(" not in cell["name"]


def test_a_dish_with_no_suffix_still_renders():
    out = day_cells({"2026-09-21": {"rice": "plain_rice"}}, ["2026-09-21"],
                    {"2026-09-21": "mix"})
    cell = out["rows"][0]["cells"]["2026-09-21"]
    assert cell["color"] == "" and cell["name"] == "Plain Rice"


def test_the_cell_key_is_slot_then_date():
    """The one string both halves must agree on."""
    marked = {"rice|2026-09-22"}
    rows = _args(pinned=marked, warned=marked, modified=marked)["rows"]
    rice = next(r for r in rows if r["id"] == "rice")
    assert rice["cells"]["2026-09-22"]["pinned"] is True
    assert rice["cells"]["2026-09-22"]["warn"] is True
    assert rice["cells"]["2026-09-22"]["modified"] is True
    # and the other day of the same slot is untouched
    assert rice["cells"]["2026-09-21"]["pinned"] is False


def test_a_non_working_day_is_labelled_rather_than_left_blank():
    """An empty column under a theme tag reads as a day the solver failed on."""
    cells = _args(off_days={"2026-09-22"})["rows"][0]["cells"]
    assert cells["2026-09-22"] == {"off": True, "name": "Not served"}
    # A served cell carries no `off` key at all; the component reads its
    # absence as falsy, so don't assert a False that is never written.
    assert not cells["2026-09-21"].get("off")


def test_a_slot_missing_on_one_day_is_a_dash_not_a_dropped_column():
    out = day_cells({"2026-09-21": {"rice": "a(Y)"}, "2026-09-22": {}},
                    DATES, THEMES)
    assert out["rows"][0]["cells"]["2026-09-22"]["name"] == "—"


def test_nonveg_is_marked_per_cell_not_per_slot():
    """A slot can hold a meat dish one day and a vegetarian one the next."""
    rows = _args(nonveg={"2026-09-21": {"nonveg_main"}})["rows"]
    nv = next(r for r in rows if r["id"] == "nonveg_main")
    assert nv["cells"]["2026-09-21"]["nonveg"] is True
    assert nv["cells"]["2026-09-22"]["nonveg"] is False


def test_every_planned_slot_becomes_a_row_once():
    ids = [r["id"] for r in _args()["rows"]]
    assert sorted(ids) == ["nonveg_main", "rice"]
    assert len(ids) == len(set(ids))


def test_days_carry_the_theme_the_pill_needs():
    days = _args()["days"]
    assert [d["iso"] for d in days] == DATES
    assert days[0]["theme"] == "mix" and days[0]["theme_label"] == "Mix"
    assert days[1]["theme"] == "chinese"


def test_a_day_with_no_theme_still_gets_a_label():
    """`theme_label` is printed; an empty string would render a blank pill."""
    out = day_cells(PLAN, DATES, {})
    assert out["days"][0]["theme_label"] == "—"


def test_color_key_ignores_a_bracket_that_is_part_of_the_name():
    assert _color_key("kadhi_(gujarati)") == ""
    assert _color_key("dal(Y)") == "Y"


if __name__ == "__main__":  # a runnable check without pytest
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
