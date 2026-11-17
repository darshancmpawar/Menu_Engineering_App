"""Dish rows the owner corrected (2026-11-17), in every city list that has them.

`corn_papad_masala_majjige` was two dishes in one row: a starter (papad corn
masala) and a welcome drink (masala majjige). `cinnamon_pears` is a drink and
is named as one. A workbook re-exported from an older copy brings them back.
"""

import pandas as pd
import pytest

from src.ontology.paths import city_excel_path


@pytest.mark.parametrize('city', ['Bangalore', 'Hyderabad'])
def test_corrected_rows(city):
    df = pd.read_excel(city_excel_path(city))
    course = dict(zip(df['item'], df['course_type']))
    assert 'corn_papad_masala_majjige' not in course
    assert 'cinnamon_pears' not in course
    assert course.get('papad_corn_masala') == 'starter'
    assert course.get('masala_majjige') == 'welcome_drink'
    assert course.get('cinnamon_pears_drink') == 'welcome_drink'
