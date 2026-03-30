"""Tests for UI formatters."""

import pytest
from ui.formatters import (
    theme_label,
    display_label_for_slot_id,
    format_item_for_ui,
    pretty_text,
    color_suffix,
    slot_sort_key,
)


def test_theme_label_monday():
    assert theme_label(0) == "Mix of South + North"


def test_theme_label_tuesday():
    assert theme_label(1) == "Chinese / Indo-Chinese"


def test_theme_label_wednesday():
    assert theme_label(2) == "Biryani Day"


def test_theme_label_thursday():
    assert theme_label(3) == "South Indian"


def test_theme_label_friday():
    assert theme_label(4) == "North Indian"


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


def test_pretty_text_strips_color():
    assert pretty_text("jeera rice (Y)") == "Jeera Rice"


def test_pretty_text_no_suffix():
    assert pretty_text("paneer butter masala") == "Paneer Butter Masala"


def test_color_suffix_present():
    assert color_suffix("dal makhani (R)") == "R"


def test_color_suffix_absent():
    assert color_suffix("dal makhani") is None


def test_slot_sort_key_known():
    k1 = slot_sort_key("welcome_drink")
    k2 = slot_sort_key("dessert")
    assert k1 < k2


def test_slot_sort_key_with_suffix():
    k = slot_sort_key("veg_dry__1")
    assert k < 999


def test_slot_sort_key_unknown():
    assert slot_sort_key("xyz_slot") == 999
