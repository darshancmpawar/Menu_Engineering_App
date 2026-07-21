"""Tests for ui/planner_view.py — the planner's pure render/export helpers
(extracted from app.py so they can be exercised without Streamlit)."""

import io

import pytest

from ui.planner_view import (
    flatten_result,
    date_label,
    menu_table_html,
    sanitize_sheet_title,
    download_filename,
    plan_xlsx,
    XLSX_MIME,
)


_SOLUTION = {
    "2026-03-23": {
        "day_type": "mix",
        "items": {
            "rice": {"item": "jeera_rice(Y)", "is_nonveg": False},
            "nonveg_main": {"item": "chicken_65(R)", "is_nonveg": True},
        },
    },
}


class TestFlattenResult:
    def test_shape(self):
        blk = flatten_result({"solution": _SOLUTION, "pool_warnings": ["w"]})
        assert blk["plan"]["2026-03-23"]["rice"] == "jeera_rice(Y)"
        assert blk["plan_dates"] == ["2026-03-23"]
        assert blk["day_types"]["2026-03-23"] == "mix"
        assert blk["nonveg"] == {"2026-03-23": {"nonveg_main"}}
        assert blk["pool_warnings"] == ["w"]
        assert blk["source"] == "solver"

    def test_empty(self):
        blk = flatten_result({})
        assert blk["plan"] == {} and blk["plan_dates"] == [] and blk["nonveg"] == {}


class TestDateLabel:
    def test_valid_iso(self):
        assert date_label("2026-03-23") == "Mon 23 Mar"

    def test_invalid_passthrough(self):
        assert date_label("not-a-date") == "not-a-date"


class TestMenuTableHtml:
    def test_headers_and_nonveg_class(self):
        plan = {"2026-03-23": {"rice": "jeera_rice(Y)", "nonveg_main": "chicken_65(R)"}}
        nonveg = {"2026-03-23": {"nonveg_main"}}
        html = menu_table_html(plan, ["2026-03-23"], {"2026-03-23": "mix"}, nonveg)
        assert "<th>Category</th>" in html
        assert "item-nonveg" in html          # the chicken cell is red
        assert "Flavoured Rice" in html        # display label for rice
        assert "Mon 23 Mar" in html

    def test_no_nonveg_map_is_safe(self):
        plan = {"2026-03-23": {"rice": "jeera_rice(Y)"}}
        html = menu_table_html(plan, ["2026-03-23"], {})
        assert "item-nonveg" not in html


class TestSanitizeSheetTitle:
    def test_strips_invalid_chars_and_caps_length(self):
        used = set()
        t = sanitize_sheet_title("North: Veg/Rice*Station [Live] with a very long name here", used)
        assert len(t) <= 31
        assert not any(c in t for c in '[]:*?/\\')

    def test_dedupes(self):
        used = set()
        a = sanitize_sheet_title("Counter", used)
        b = sanitize_sheet_title("Counter", used)
        assert a == "Counter" and b != a and b.lower() in used


class TestDownloadFilename:
    def test_date_range(self):
        blocks = [{"plan": {"x": 1}, "plan_dates": ["2026-07-20", "2026-07-24"]}]
        assert download_filename(blocks, "Acme Corp") == "menu_Acme_Corp_2026-07-20_to_2026-07-24.xlsx"

    def test_single_date(self):
        blocks = [{"plan": {"x": 1}, "plan_dates": ["2026-07-20"]}]
        assert download_filename(blocks, "Acme") == "menu_Acme_2026-07-20.xlsx"

    def test_no_dates(self):
        assert download_filename([{"plan": {}}], "Empty") == "menu_Empty.xlsx"

    def test_sanitizes_client(self):
        assert download_filename([], "Café #1").startswith("menu_Caf_1")


class TestPlanXlsx:
    def test_roundtrip_sheet_and_nonveg_font(self):
        openpyxl = pytest.importorskip("openpyxl")
        blocks = [{
            "name": "Main",
            "plan": {"2026-03-23": {"rice": "jeera_rice(Y)", "nonveg_main": "chicken_65(R)"}},
            "plan_dates": ["2026-03-23"],
            "nonveg": {"2026-03-23": {"nonveg_main"}},
        }]
        data = plan_xlsx(blocks, "Main")
        assert isinstance(data, bytes) and len(data) > 0
        wb = openpyxl.load_workbook(io.BytesIO(data))
        assert wb.sheetnames == ["Main"]
        ws = wb["Main"]
        assert ws["A1"].value == "Main"            # title row
        assert ws["A2"].value == "Category"        # header row
        # Find the non-veg cell and confirm it's red.
        reds = [c.value for row in ws.iter_rows() for c in row
                if c.font and c.font.color and c.font.color.rgb and "C40D1B" in str(c.font.color.rgb)]
        assert any("Chicken 65" in str(v) for v in reds)

    def test_empty_blocks_still_valid(self):
        openpyxl = pytest.importorskip("openpyxl")
        data = plan_xlsx([], "Nobody")
        wb = openpyxl.load_workbook(io.BytesIO(data))
        assert wb.sheetnames == ["Menu"]

    def test_mime_constant(self):
        assert XLSX_MIME.endswith("spreadsheetml.sheet")
