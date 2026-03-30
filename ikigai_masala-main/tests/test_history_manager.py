"""Tests for HistoryManager."""

import datetime as dt
import pandas as pd
import pytest
from src.history.history_manager import HistoryManager


def _make_long_df():
    """Create synthetic long history."""
    return pd.DataFrame([
        {'service_date': '2026-03-01', 'slot': 'rice', 'item_base': 'jeera rice', 'client_name': 'Rippling'},
        {'service_date': '2026-03-02', 'slot': 'rice', 'item_base': 'lemon rice', 'client_name': 'Rippling'},
        {'service_date': '2026-03-03', 'slot': 'bread', 'item_base': 'rice roti', 'client_name': 'Rippling'},
        {'service_date': '2026-03-10', 'slot': 'rice', 'item_base': 'pulao', 'client_name': 'Stripe'},
        {'service_date': '2026-03-15', 'slot': 'white_rice', 'item_base': 'steamed rice', 'client_name': 'Rippling'},
    ])


def _make_weeks_df():
    return pd.DataFrame([
        {'week_start': '2026-03-02', 'week_signature': 'sig1', 'client_name': 'Rippling'},
        {'week_start': '2026-02-15', 'week_signature': 'sig2', 'client_name': 'Rippling'},
    ])


class TestHistoryManager:
    def test_load_from_dataframes(self):
        hm = HistoryManager().load_from_dataframes(_make_long_df(), _make_weeks_df())
        assert hm._long is not None
        assert hm._weeks is not None

    def test_empty_history(self):
        hm = HistoryManager()
        dates = [dt.date(2026, 3, 20)]
        bans = hm.banned_items_by_date(dates)
        assert bans[dates[0]] == set()

    def test_banned_items(self):
        hm = HistoryManager().load_from_dataframes(_make_long_df())
        dates = [dt.date(2026, 3, 20)]
        bans = hm.banned_items_by_date(dates, cooldown_days=20)
        # Items from March 1-19 within 20 day window of March 20
        assert 'jeera rice' in bans[dates[0]]
        assert 'lemon rice' in bans[dates[0]]

    def test_banned_items_excludes_const_slots(self):
        hm = HistoryManager().load_from_dataframes(_make_long_df())
        dates = [dt.date(2026, 3, 20)]
        bans = hm.banned_items_by_date(dates, cooldown_days=20, const_slots=['white_rice'])
        assert 'steamed rice' not in bans[dates[0]]

    def test_banned_items_excludes_repeatable(self):
        hm = HistoryManager().load_from_dataframes(_make_long_df())
        dates = [dt.date(2026, 3, 20)]
        bans = hm.banned_items_by_date(
            dates, cooldown_days=20, repeatable_items={'jeera rice'}
        )
        assert 'jeera rice' not in bans[dates[0]]

    def test_filter_by_client(self):
        hm = HistoryManager().load_from_dataframes(_make_long_df(), _make_weeks_df())
        filtered = hm.filter_by_client('Rippling')
        dates = [dt.date(2026, 3, 20)]
        bans = filtered.banned_items_by_date(dates, cooldown_days=20)
        assert 'pulao' not in bans[dates[0]]  # Stripe item

    def test_recent_week_signatures(self):
        hm = HistoryManager().load_from_dataframes(weeks_df=_make_weeks_df())
        sigs = hm.recent_week_signatures(dt.date(2026, 3, 16), cooldown_days=30)
        assert 'sig1' in sigs
        assert 'sig2' in sigs

    def test_ricebread_ban(self):
        hm = HistoryManager().load_from_dataframes(_make_long_df())
        dates = [dt.date(2026, 3, 10)]
        result = hm.ricebread_ban_by_date(dates, ricebread_items={'rice roti'}, gap_days=10)
        assert result[dates[0]] is True

    def test_ricebread_no_ban(self):
        hm = HistoryManager().load_from_dataframes(_make_long_df())
        dates = [dt.date(2026, 3, 20)]
        result = hm.ricebread_ban_by_date(dates, ricebread_items={'rice roti'}, gap_days=10)
        assert result[dates[0]] is False

    def test_compute_week_signature(self):
        plan = {
            dt.date(2026, 3, 16): {'rice': 'jeera rice', 'bread': 'naan'},
            dt.date(2026, 3, 17): {'rice': 'lemon rice', 'bread': 'roti'},
        }
        dates = [dt.date(2026, 3, 16), dt.date(2026, 3, 17)]
        sig = HistoryManager.compute_week_signature(plan, dates)
        assert '2026-03-16' in sig
        assert 'rice=jeera rice' in sig

    def test_parse_signature(self):
        sig = '2026-03-16|rice=jeera rice|bread=naan|2026-03-17|rice=lemon rice'
        result = HistoryManager.parse_signature_to_expected_map(sig)
        assert result[('2026-03-16', 'rice')] == 'jeera rice'
        assert result[('2026-03-17', 'rice')] == 'lemon rice'

    def test_save_and_reload(self, tmp_path):
        plan = {
            dt.date(2026, 3, 16): {'rice': 'jeera rice', 'bread': 'naan'},
        }
        dates = [dt.date(2026, 3, 16)]
        long_path = str(tmp_path / 'history_long.csv')
        weeks_path = str(tmp_path / 'history_weeks.csv')

        hm = HistoryManager()
        hm.save(plan, dates, 'Rippling', dt.date(2026, 3, 16), 'test_sig', long_path, weeks_path)

        # Reload and verify
        hm2 = HistoryManager().load(long_path, weeks_path)
        assert hm2._long is not None
        assert len(hm2._long) == 2  # rice + bread
        assert hm2._weeks is not None
        assert len(hm2._weeks) == 1
