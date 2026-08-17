"""Tests for src/solver/_helpers.py shared utilities."""

import datetime as dt

from src.solver._helpers import (
    weekday_type,
    theme_label,
    strip_color_suffix,
    resolve_alternating_theme,
    weekday_type_for_config,
)


class TestAlternatingTheme:
    def test_resolve_even_iso_week_is_chinese(self):
        d = dt.date(2026, 1, 8)  # ISO week 2 (even)
        assert d.isocalendar()[1] % 2 == 0
        assert resolve_alternating_theme('chinese_continental', d) == 'chinese'

    def test_resolve_odd_iso_week_is_continental(self):
        d = dt.date(2026, 1, 13)  # ISO week 3 (odd)
        assert d.isocalendar()[1] % 2 == 1
        assert resolve_alternating_theme('chinese_continental', d) == 'continental'

    def test_non_alternating_theme_passthrough(self):
        d = dt.date(2026, 1, 13)
        assert resolve_alternating_theme('south', d) == 'south'

    def test_weekday_type_for_config_resolves_alternation(self):
        tm = {'tuesday': 'chinese_continental'}
        assert weekday_type_for_config(dt.date(2026, 1, 6), tm) == 'chinese'      # ISO wk 2
        assert weekday_type_for_config(dt.date(2026, 1, 13), tm) == 'continental'  # ISO wk 3

    def test_continental_label(self):
        assert theme_label('continental') == 'Continental'


class TestWeekdayType:
    def test_monday_mix(self):
        d = dt.date(2026, 3, 23)  # Monday
        assert weekday_type(d) == 'mix'

    def test_tuesday_chinese(self):
        d = dt.date(2026, 3, 24)  # Tuesday
        assert weekday_type(d) == 'chinese'

    def test_wednesday_biryani(self):
        d = dt.date(2026, 3, 25)  # Wednesday
        assert weekday_type(d) == 'biryani'

    def test_thursday_south(self):
        d = dt.date(2026, 3, 26)  # Thursday
        assert weekday_type(d) == 'south'

    def test_friday_north(self):
        d = dt.date(2026, 3, 27)  # Friday
        assert weekday_type(d) == 'north'

    def test_saturday_holiday(self):
        d = dt.date(2026, 3, 28)  # Saturday
        assert weekday_type(d) == 'holiday'

    def test_sunday_holiday(self):
        d = dt.date(2026, 3, 29)  # Sunday
        assert weekday_type(d) == 'holiday'


class TestThemeLabel:
    def test_mix(self):
        assert theme_label('mix') == 'Mix of South + North'

    def test_chinese(self):
        assert theme_label('chinese') == 'Chinese'

    def test_biryani(self):
        assert theme_label('biryani') == 'Biryani'

    def test_south(self):
        assert theme_label('south') == 'South Indian'

    def test_north(self):
        assert theme_label('north') == 'North Indian'

    def test_unknown_capitalizes(self):
        assert theme_label('special') == 'Special'


class TestStripColorSuffix:
    def test_with_suffix(self):
        assert strip_color_suffix('jeera rice(R)') == 'jeera rice'

    def test_with_suffix_spaces(self):
        assert strip_color_suffix('dal makhani (Y) ') == 'dal makhani'

    def test_without_suffix(self):
        assert strip_color_suffix('paneer butter masala') == 'paneer butter masala'

    def test_empty_string(self):
        assert strip_color_suffix('') == ''

    def test_none(self):
        assert strip_color_suffix(None) == ''
