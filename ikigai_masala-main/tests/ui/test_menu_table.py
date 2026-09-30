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

import sys
from pathlib import Path

# So `python tests/ui/test_menu_table.py` works as the pytest-free check the
# bottom of this file promises; pytest.ini already puts the root on the path
# for the normal run, and adding it twice is harmless.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ui.menu_table import (  # noqa: E402 — after the path insert, on purpose
    _color_key, cell_keys, day_cells, explain_days, regen_request,
    warned_cells,
)
from ui.theme_tokens import ITEM_COLOR_MAP, ITEM_DOT_COLOR

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
    names the colour and must not also print in the name."""
    cell = _args()["rows"][0]["cells"]["2026-09-21"]
    assert cell["color"] == "Y"
    assert cell["name"] == "Veg Fried Rice"
    assert "(" not in cell["name"]


def test_the_colour_becomes_a_swatch_and_a_readable_foreground():
    """Two colours per cell, for two jobs.

    `color_dot` is the swatch the cell draws beside the dish; `color_fg` is the
    readable version, used where the colour has to carry TEXT — the dish names
    in the explain paragraph. For every colour but one they are the same value,
    and the one exception is the whole reason there are two.
    """
    cell = _args()["rows"][0]["cells"]["2026-09-21"]
    assert cell["color"] == "Y"
    assert cell["color_dot"] == ITEM_DOT_COLOR["Y"]
    assert cell["color_fg"] == ITEM_COLOR_MAP["Y"][2]


def test_white_is_a_white_swatch_but_never_white_text():
    """The exception, stated both ways. A white dot is drawn as white and the
    component outlines it; white TEXT on a white cell is an empty cell, so the
    foreground is the readable grey instead."""
    out = day_cells({"2026-09-21": {"rice": "jeera_rice(W)"}}, ["2026-09-21"], {})
    cell = out["rows"][0]["cells"]["2026-09-21"]
    assert cell["color_dot"] == "#FFFFFF"
    assert cell["color_fg"].lower() not in ("#fff", "#ffffff")


def test_a_dish_with_no_suffix_still_renders():
    out = day_cells({"2026-09-21": {"rice": "plain_rice"}}, ["2026-09-21"],
                    {"2026-09-21": "mix"})
    cell = out["rows"][0]["cells"]["2026-09-21"]
    assert cell["color"] == "" and cell["name"] == "Plain Rice"
    # No colour → no swatch and no ink, rather than a black dot standing in.
    assert cell["color_dot"] == "" and cell["color_fg"] == ""


def test_an_unknown_colour_letter_does_not_invent_a_colour():
    out = day_cells({"2026-09-21": {"rice": "mystery_rice(Z)"}}, ["2026-09-21"], {})
    cell = out["rows"][0]["cells"]["2026-09-21"]
    assert cell["color"] == "Z" and cell["color_dot"] == ""


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


def test_a_shared_row_is_matched_on_the_base_slot():
    """`shared_categories` is configured as `dal`; the counter serves `dal__1`
    and `dal__2`. Matching the whole slot id would label neither."""
    rows = day_cells({"2026-09-21": {"dal__1": "a(Y)", "rice": "b(W)"}},
                     ["2026-09-21"], {}, shared={"dal"})["rows"]
    by_id = {r["id"]: r["shared"] for r in rows}
    assert by_id == {"dal__1": True, "rice": False}


# --- the two converters the markers arrive through -------------------------

def test_cell_keys_turns_a_projection_into_the_table_key():
    """`{date: {slot}}` is what every `ui.formatters` projection returns;
    `"<slot>|<date>"` is what the table reads. One converter, or the pins
    render as a plan with nothing pinned."""
    assert cell_keys({"2026-09-21": {"rice", "dal__1"}}) == {
        "rice|2026-09-21", "dal__1|2026-09-21"}
    assert cell_keys(None) == set()


def test_a_warning_marks_every_expanded_cell_of_its_base_slot():
    """Diagnostics address `rice`; the plan holds `rice__1` and `rice__2`."""
    plan = {"2026-09-21": {"rice__1": "a(W)", "rice__2": "b(Y)", "dal": "c(Y)"}}
    diags = [{"severity": "warning",
              "affected": {"date": "2026-09-21", "slot": "rice"}}]
    assert warned_cells(diags, plan) == {"rice__1|2026-09-21", "rice__2|2026-09-21"}


def test_an_info_diagnostic_is_not_a_cell_marker():
    """"Exactly enough items, no variety" is true of every staple by design.
    Marking them all is a marker nobody reads."""
    plan = {"2026-09-21": {"rice": "a(W)"}}
    assert warned_cells(
        [{"severity": "info", "affected": {"date": "2026-09-21", "slot": "rice"}}],
        plan) == set()


def test_a_whole_solve_diagnostic_is_not_spread_over_every_cell():
    plan = {"2026-09-21": {"rice": "a(W)"}}
    assert warned_cells(
        [{"severity": "warning", "affected": {"max_per_week": 2}}], plan) == set()
    assert warned_cells(None, plan) == set()


# --- the regenerate request ------------------------------------------------

def test_a_request_splits_back_into_the_replace_mask():
    """The mask `/regenerate` takes. Split the key the other way round and it
    is a valid-looking dict naming no cell the plan has."""
    req = regen_request({"action": "regenerate", "nonce": 1,
                         "cells": ["rice|2026-09-21", "dal__1|2026-09-21",
                                   "rice|2026-09-22"]})
    assert req["cells"] == {"2026-09-21": ["rice", "dal__1"],
                            "2026-09-22": ["rice"]}
    assert req["nonce"] == 1


def test_the_same_request_is_handled_once():
    """A component's return value is replayed on every rerun and handling a
    regenerate ends in a rerun. Without this the table regenerates forever."""
    picked = {"action": "regenerate", "nonce": 7, "cells": ["rice|2026-09-21"]}
    assert regen_request(picked, last_nonce=None) is not None
    assert regen_request(picked, last_nonce=7) is None
    # a second press stamps a new nonce and is handled again
    assert regen_request({**picked, "nonce": 8}, last_nonce=7) is not None


def test_nothing_to_do_is_none_not_an_empty_regenerate():
    """An empty mask would re-solve the WHOLE plan, not nothing."""
    assert regen_request(None) is None
    assert regen_request({"action": "regenerate", "cells": []}) is None
    assert regen_request({"action": "regenerate", "cells": ["rubbish"]}) is None
    assert regen_request({"action": "something_else", "cells": ["a|b"]}) is None


# --- "Why this menu" -------------------------------------------------------

PAYLOAD = {"days": [
    {"date": "2026-09-21", "overview": "Rajma with jeera rice.",
     "checks": [{"name": "colour_variety", "detail": "4 colours", "passed": True},
                {"name": "texture_contrast", "detail": "nothing crisp",
                 "passed": False}]},
    {"date": "2026-09-22", "overview": "", "checks": []},
]}


def test_a_day_is_offered_only_when_there_is_something_to_say():
    """The component renders the button off this lookup, and the panel is
    guarded on the same one. An entry with no overview and no checks would put
    a control on screen that opens nothing — which is what it did."""
    got = explain_days(PAYLOAD)
    assert sorted(got) == ["2026-09-21"]


def test_a_check_reads_as_one_sentence_and_keeps_its_verdict():
    checks = explain_days(PAYLOAD)["2026-09-21"]["checks"]
    assert checks[0] == {"text": "colour variety — 4 colours", "passed": True}
    assert checks[1]["passed"] is False


def test_a_missing_verdict_is_not_read_as_a_failure():
    """`passed` absent means the check did not report one; only an explicit
    False is a warning. Defaulting the other way paints a day with ticks it
    never earned."""
    out = explain_days({"days": [{"date": "2026-09-21", "overview": "x",
                                  "checks": [{"name": "a", "detail": "b"}]}]})
    assert out["2026-09-21"]["checks"][0]["passed"] is True


def test_nothing_to_explain_is_an_empty_map_not_a_crash():
    assert explain_days(None) == {} and explain_days({}) == {}
    assert explain_days({"days": []}) == {}


if __name__ == "__main__":  # a runnable check without pytest
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
