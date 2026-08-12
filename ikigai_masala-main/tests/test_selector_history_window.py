"""Cross-week cadence via saved history (SelectorHistoryWindowRule).

A selector may recur only once per rolling window that is longer than a single
plan. The window is read from menu_history and folded into banned_by_date. These
pin the ban logic, the selector -> item resolution, the loader wiring, and the
history-lookback widening.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from src.history.history_manager import HistoryManager
from src.menu_rules.menu_rule_loader import MenuRuleLoader
from src.menu_rules.selector_history_window_rule import SelectorHistoryWindowRule

DATES = [dt.date(2026, 8, 3), dt.date(2026, 8, 4), dt.date(2026, 8, 5)]


def _hm(rows):
    long = pd.DataFrame(rows)
    return HistoryManager().load_from_dataframes(long_df=long).filter_by_client('c')


# --- HistoryManager.selector_banned_by_date --------------------------------

class TestSelectorBannedByDate:
    def test_recent_occurrence_bans_the_whole_selector(self):
        hm = _hm([{'client_name': 'c', 'service_date': '2026-07-30',
                   'item_base': 'fish_curry', 'slot': 'nonveg_main'}])
        bans = hm.selector_banned_by_date(DATES, {'fish_curry', 'goan_fish_curry'}, 15)
        assert bans[DATES[0]] == {'fish_curry', 'goan_fish_curry'}

    def test_occurrence_outside_window_does_not_ban(self):
        # 2026-07-30 is 4 days before the plan; a 3-day window excludes it.
        hm = _hm([{'client_name': 'c', 'service_date': '2026-07-30',
                   'item_base': 'fish_curry', 'slot': 'nonveg_main'}])
        assert hm.selector_banned_by_date(DATES, {'fish_curry'}, 3)[DATES[0]] == set()

    def test_no_history_bans_nothing(self):
        hm = HistoryManager().load_from_dataframes(long_df=None)
        assert hm.selector_banned_by_date(DATES, {'fish_curry'}, 15)[DATES[0]] == set()

    def test_unrelated_history_bans_nothing(self):
        hm = _hm([{'client_name': 'c', 'service_date': '2026-07-30',
                   'item_base': 'chicken_65', 'slot': 'nonveg_main'}])
        assert hm.selector_banned_by_date(DATES, {'fish_curry'}, 15)[DATES[0]] == set()


# --- the rule ---------------------------------------------------------------

class TestRule:
    def test_validates_and_reads_window(self):
        r = SelectorHistoryWindowRule({
            'name': 'x', 'type': 'selector_history_window',
            'selector': {'flag': 'is_fish_dish'}, 'window_days': 15})
        assert r.validate_config()
        assert r.window_days == 15

    def test_missing_window_is_invalid(self):
        r = SelectorHistoryWindowRule({
            'name': 'x', 'selector': {'flag': 'is_fish_dish'}})
        assert not r.validate_config()

    def test_missing_selector_is_invalid(self):
        r = SelectorHistoryWindowRule({'name': 'x', 'window_days': 15})
        assert not r.validate_config()

    def test_matching_items_resolves_fish_in_ncr(self):
        from src.ontology.paths import city_excel_path
        df = pd.read_excel(city_excel_path('NCR'))
        df.columns = [c.strip() for c in df.columns]
        r = SelectorHistoryWindowRule({
            'name': 'x', 'selector': {'flag': 'is_fish_dish'}, 'window_days': 15})
        items = r.matching_items(df)
        assert 'fish_curry' in items and 'goan_fish_curry' in items

    def test_matching_items_resolves_sambar_by_course_type(self):
        from src.ontology.paths import city_excel_path
        df = pd.read_excel(city_excel_path('NCR'))
        df.columns = [c.strip() for c in df.columns]
        r = SelectorHistoryWindowRule({
            'name': 'x', 'selector': {'course_type': 'sambar'}, 'window_days': 15})
        assert len(r.matching_items(df)) >= 10

    def test_matching_items_is_scoped_to_base_slot(self):
        # 'leafy veg_dry once per 15 days' must not match a leafy DAL: the ban is
        # scoped to the rule's base_slot, so a leafy dal in history never trips
        # the veg_dry cadence (the Pune R31 regression).
        from src.ontology.paths import city_excel_path
        df = pd.read_excel(city_excel_path('Pune'))
        df.columns = [c.strip() for c in df.columns]
        r = SelectorHistoryWindowRule({
            'name': 'x', 'base_slot': 'veg_dry',
            'selector': {'flag': 'is_leafy_based_dish'}, 'window_days': 15})
        items = r.matching_items(df)
        assert items, "expected some leafy veg_dry items"
        assert 'dal_palak' not in items  # a leafy dal, not a veg_dry
        # every matched item really is a veg_dry
        vd = set(df[df['course_type'] == 'veg_dry']['item'].astype(str).str.strip())
        assert items <= {v.lower() for v in vd}


# --- loader wiring ----------------------------------------------------------

class TestLoaderWiring:
    def test_type_is_registered(self):
        rules = MenuRuleLoader().load_for_city('bangalore')
        assert any(isinstance(r, SelectorHistoryWindowRule) for r in rules)

    def test_stryker_has_the_ncr_windows(self):
        loader = MenuRuleLoader()
        city = loader.load_for_city('ncr')
        rules = loader.load_for_client('Stryker NCR', city)
        names = {r.name for r in rules if isinstance(r, SelectorHistoryWindowRule)}
        assert {'strykerncr_fish_15d_window', 'strykerncr_biryani_15d_window',
                'strykerncr_sambar_15d_window'} <= names


# --- integration: the ban reaches banned_by_date ---------------------------

def test_history_context_merges_selector_window_into_banned(monkeypatch):
    """A fish served 4 days ago is banned on the plan dates via the window."""
    from tests.fake_supabase import FakeSupabase
    import src.db as db_mod
    from src.application.history import _build_history_context
    from src.ontology.paths import city_excel_path

    fake = FakeSupabase(seed={
        'clients': [], 'app_settings': [], 'week_signatures': [],
        'menu_history': [{'client_name': 'Stryker NCR',
                          'service_date': '2026-07-30',
                          'menu': {'nonveg_main': 'fish_curry'}}],
    })
    monkeypatch.setattr(db_mod, '_sb_client', fake, raising=False)

    df = pd.read_excel(city_excel_path('NCR'))
    df.columns = [c.strip() for c in df.columns]
    fish = SelectorHistoryWindowRule({
        'name': 'fish', 'selector': {'flag': 'is_fish_dish'}, 'window_days': 15})
    dates = [dt.date(2026, 8, 3), dt.date(2026, 8, 4)]
    banned, _rb, _sig = _build_history_context(
        df, 'Stryker NCR', dt.date(2026, 8, 3), dates, window_days=45,
        selector_windows=[(fish.matching_items(df), 15)])
    assert 'fish_curry' in banned[dates[0]]


def test_history_context_no_ban_when_occurrence_is_old(monkeypatch):
    from tests.fake_supabase import FakeSupabase
    import src.db as db_mod
    from src.application.history import _build_history_context
    from src.ontology.paths import city_excel_path

    fake = FakeSupabase(seed={
        'clients': [], 'app_settings': [], 'week_signatures': [],
        'menu_history': [{'client_name': 'Stryker NCR',
                          'service_date': '2026-07-01',  # 33 days before
                          'menu': {'nonveg_main': 'fish_curry'}}],
    })
    monkeypatch.setattr(db_mod, '_sb_client', fake, raising=False)

    df = pd.read_excel(city_excel_path('NCR'))
    df.columns = [c.strip() for c in df.columns]
    fish = SelectorHistoryWindowRule({
        'name': 'fish', 'selector': {'flag': 'is_fish_dish'}, 'window_days': 15})
    dates = [dt.date(2026, 8, 3)]
    banned, _rb, _sig = _build_history_context(
        df, 'Stryker NCR', dt.date(2026, 8, 3), dates, window_days=45,
        selector_windows=[(fish.matching_items(df), 15)])
    assert 'fish_curry' not in banned.get(dates[0], set())
