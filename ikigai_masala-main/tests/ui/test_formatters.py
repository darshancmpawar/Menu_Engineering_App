"""Tests for UI formatters."""

from ui.formatters import (
    display_label_for_slot_id,
    flatten_api_solution,
    format_item_for_ui,
    format_item_html,
    nonveg_slots_from_solution,
    shared_items_from_solution,
    slot_sort_key,
)


def test_display_label_known_slot():
    label = display_label_for_slot_id("welcome_drink")
    assert isinstance(label, str)
    assert len(label) > 0


def test_display_label_unknown_slot():
    label = display_label_for_slot_id("some_unknown_slot")
    assert "Some Unknown Slot" == label


def test_format_item_for_ui():
    assert format_item_for_ui("  jeera_rice(Y)  ") == "Jeera Rice"
    assert format_item_for_ui("dal_tadka(R)") == "Dal Tadka"
    assert format_item_for_ui("steamed rice") == "Steamed Rice"
    assert format_item_for_ui("") == ""
    assert format_item_for_ui(None) == ""


def test_slot_sort_key_known():
    k1 = slot_sort_key("welcome_drink")
    k2 = slot_sort_key("dessert")
    assert k1 < k2


def test_slot_sort_key_with_suffix():
    k = slot_sort_key("veg_dry__1")
    assert k < 999


def test_slot_sort_key_unknown():
    assert slot_sort_key("xyz_slot") == 999


def test_format_item_html_escapes_html_in_item_name():
    # Admins can edit Supabase/Excel, and the rendered output goes into
    # st.markdown(..., unsafe_allow_html=True). The item name must be
    # HTML-escaped so tag-like strings render as text, not markup.
    out = format_item_html("<script>alert(1)</script>(Y)")
    lower = out.lower()
    assert "<script>" not in lower
    assert "</script>" not in lower
    assert "&lt;script&gt;" in lower
    assert "&lt;/script&gt;" in lower
    # Structural markup we emit ourselves still passes through.
    assert '<span class="item-name">' in out
    assert '<span class="color-pill"' in out


def test_format_item_html_escapes_without_color_suffix():
    out = format_item_html("<b>bold</b>")
    lower = out.lower()
    assert "<b>" not in lower
    assert "</b>" not in lower
    assert "&lt;b&gt;" in lower
    assert "&lt;/b&gt;" in lower


def test_flatten_api_solution_rich_format():
    raw = {
        "2026-03-23": {
            "theme": "mix",
            "day_type": "mix",
            "items": {
                "bread": {"item": "plain_chapatti(B)", "item_base": "plain_chapatti"},
                "rice": {"item": "jeera_rice(Y)"},
            },
        },
    }
    flat, day_types = flatten_api_solution(raw)
    assert flat == {"2026-03-23": {"bread": "plain_chapatti(B)", "rice": "jeera_rice(Y)"}}
    assert day_types == {"2026-03-23": "mix"}


def test_flatten_api_solution_flat_legacy_format():
    raw = {"2026-03-23": {"bread": "plain_chapatti(B)"}}
    flat, day_types = flatten_api_solution(raw)
    assert flat == {"2026-03-23": {"bread": "plain_chapatti(B)"}}
    assert day_types == {}


def test_flatten_api_solution_empty():
    assert flatten_api_solution({}) == ({}, {})


def test_flatten_api_solution_falls_back_to_item_base():
    raw = {
        "2026-03-23": {
            "day_type": "south",
            "items": {"bread": {"item_base": "plain_chapatti"}},
        },
    }
    flat, _ = flatten_api_solution(raw)
    assert flat["2026-03-23"]["bread"] == "plain_chapatti"


def test_format_item_html_nonveg_adds_red_class():
    out = format_item_html("chicken_65(R)", is_nonveg=True)
    assert 'item-nonveg' in out
    veg = format_item_html("paneer_tikka(G)", is_nonveg=False)
    assert 'item-nonveg' not in veg


def test_nonveg_slots_from_solution():
    raw = {
        "2026-03-23": {
            "day_type": "mix",
            "items": {
                "nonveg_main": {"item": "chicken_65(R)", "is_nonveg": True},
                "rice": {"item": "jeera_rice(Y)", "is_nonveg": False},
                "veg_dry__1": {"item": "aloo_jeera(Y)", "is_nonveg": False},
            },
        },
    }
    nv = nonveg_slots_from_solution(raw)
    assert nv == {"2026-03-23": {"nonveg_main"}}


def test_nonveg_slots_from_solution_empty_when_all_veg():
    raw = {"2026-03-23": {"items": {"rice": {"item": "jeera_rice(Y)", "is_nonveg": False}}}}
    assert nonveg_slots_from_solution(raw) == {}


# --- shared_items_from_solution (cross-counter common categories) -----------

def _sol():
    return {
        "2026-08-03": {"day_type": "north", "items": {
            "rice": {"item": "masala_khuska(Y)", "item_base": "masala_khuska"},
            "bread": {"item": "plain_chapatti", "item_base": "plain_chapatti"},
            "veg_dry__1": {"item": "aloo_jeera(Y)", "item_base": "aloo_jeera"},
            "nonveg_main": {"item": "chicken_65(R)", "item_base": "chicken_65"},
        }},
        "2026-08-04": {"day_type": "mix", "items": {
            "rice": {"item": "mutter_pulao(Y)", "item_base": "mutter_pulao"},
            "bread": {"item": "plain_phulka", "item_base": "plain_phulka"},
        }},
    }


def test_shared_items_extracts_only_shared_base_slots():
    got = shared_items_from_solution(_sol(), ["rice", "bread"])
    # veg_dry / nonveg_main are not shared, so they are excluded.
    assert ["2026-08-03", "rice", "masala_khuska"] in got
    assert ["2026-08-03", "bread", "plain_chapatti"] in got
    assert ["2026-08-04", "rice", "mutter_pulao"] in got
    assert ["2026-08-04", "bread", "plain_phulka"] in got
    assert all(row[1].split("__")[0] in {"rice", "bread"} for row in got)
    assert len(got) == 4


def test_shared_items_matches_expanded_slot_by_base():
    got = shared_items_from_solution(_sol(), ["veg_dry"])
    # base 'veg_dry' must catch the expanded 'veg_dry__1' cell.
    assert got == [["2026-08-03", "veg_dry__1", "aloo_jeera"]]


def test_shared_items_empty_when_no_shared_categories():
    assert shared_items_from_solution(_sol(), []) == []
    assert shared_items_from_solution(_sol(), None) == []


def test_shared_items_tolerates_missing_items_key():
    raw = {"2026-08-03": {"day_type": "north"}}  # no 'items'
    assert shared_items_from_solution(raw, ["rice"]) == []
