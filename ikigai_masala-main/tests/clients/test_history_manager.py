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

    def test_save_writes_to_supabase(self):
        """save() writes one JSONB row per day (menu={slot:item}) + a week
        signature, deleting any previous rows for the same (client, dates)
        first so re-saving overwrites."""
        from tests.fake_supabase import FakeSupabase
        fake = FakeSupabase(seed={'menu_history': [], 'week_signatures': []})
        plan = {
            dt.date(2026, 3, 16): {'rice': 'jeera rice', 'bread': 'naan'},
        }
        dates = [dt.date(2026, 3, 16)]

        hm = HistoryManager()
        hm.save(plan, dates, 'Rippling', dt.date(2026, 3, 16), 'test_sig',
                supabase_client=fake)

        rows = fake.rows('menu_history')
        assert len(rows) == 1  # one row per day, not per dish
        assert rows[0]['client_name'] == 'Rippling'
        assert rows[0]['menu'] == {'rice': 'jeera rice', 'bread': 'naan'}
        sigs = fake.rows('week_signatures')
        assert len(sigs) == 1
        assert sigs[0]['week_signature'] == 'test_sig'

    def test_save_skips_empty_days(self):
        """A day with no items produces no row (keeps 'partial coverage'
        distinguishable from 'fully saved')."""
        from tests.fake_supabase import FakeSupabase
        fake = FakeSupabase(seed={'menu_history': [], 'week_signatures': []})
        hm = HistoryManager()
        hm.save(
            {dt.date(2026, 3, 16): {'rice': 'jeera rice'},
             dt.date(2026, 3, 17): {}},
            [dt.date(2026, 3, 16), dt.date(2026, 3, 17)],
            'Rippling', dt.date(2026, 3, 16), 'sig', supabase_client=fake,
        )
        rows = fake.rows('menu_history')
        assert len(rows) == 1
        assert rows[0]['service_date'] == '2026-03-16'

    def test_save_overwrites_existing_rows_for_same_dates(self):
        """A second save for the same (client, date) replaces the day row."""
        from tests.fake_supabase import FakeSupabase
        fake = FakeSupabase(seed={'menu_history': [], 'week_signatures': []})
        dates = [dt.date(2026, 3, 16)]
        hm = HistoryManager()

        hm.save({dt.date(2026, 3, 16): {'rice': 'jeera rice'}},
                dates, 'Rippling', dt.date(2026, 3, 16),
                'sig_a', supabase_client=fake)
        rows = fake.rows('menu_history')
        assert len(rows) == 1 and rows[0]['menu'] == {'rice': 'jeera rice'}

        hm.save({dt.date(2026, 3, 16): {'rice': 'biryani'}},
                dates, 'Rippling', dt.date(2026, 3, 16),
                'sig_b', supabase_client=fake)
        rows = fake.rows('menu_history')
        assert len(rows) == 1 and rows[0]['menu'] == {'rice': 'biryani'}
        sigs = fake.rows('week_signatures')
        assert len(sigs) == 1 and sigs[0]['week_signature'] == 'sig_b'

    def test_save_only_overwrites_for_matching_client(self):
        """Re-saving for Rippling must not touch Stripe's day row for the
        same date — the delete filter is keyed on client_name."""
        from tests.fake_supabase import FakeSupabase
        fake = FakeSupabase(seed={
            'menu_history': [
                {'client_name': 'Stripe', 'service_date': '2026-03-16',
                 'menu': {'rice': 'stripe rice'}},
            ],
            'week_signatures': [],
        })

        hm = HistoryManager()
        hm.save({dt.date(2026, 3, 16): {'rice': 'jeera rice'}},
                [dt.date(2026, 3, 16)], 'Rippling', dt.date(2026, 3, 16),
                'sig_a', supabase_client=fake)
        clients = {r['client_name'] for r in fake.rows('menu_history')}
        assert clients == {'Stripe', 'Rippling'}

    def test_save_requires_supabase_client(self):
        hm = HistoryManager()
        with pytest.raises(ValueError):
            hm.save({}, [], 'Rippling', dt.date(2026, 3, 16), 'sig',
                    supabase_client=None)

    def test_save_counters_writes_nested_menu(self):
        from tests.fake_supabase import FakeSupabase
        fake = FakeSupabase(seed={'menu_history': [], 'week_signatures': []})
        hm = HistoryManager()
        d = dt.date(2026, 3, 16)
        hm.save_counters(
            [
                ('Main', {d: {'rice': 'jeera rice', 'dal': 'tadka'}}),
                ('Live', {d: {'starter': 'tikka'}}),
            ],
            [d], 'Rippling', d, 'sig', supabase_client=fake,
        )
        rows = fake.rows('menu_history')
        assert len(rows) == 1
        assert rows[0]['menu'] == {
            'Main': {'rice': 'jeera rice', 'dal': 'tadka'},
            'Live': {'starter': 'tikka'},
        }
        assert len(fake.rows('week_signatures')) == 1


class TestLoadSavedPlan:
    """Verify the readback path used by /api/v1/saved-plan (JSON day rows)."""

    def _seed(self, rows):
        from tests.fake_supabase import FakeSupabase
        return FakeSupabase(seed={'menu_history': rows})

    def test_returns_empty_when_no_rows(self):
        fake = self._seed([])
        out = HistoryManager.load_saved_plan(
            fake, 'Rippling', [dt.date(2026, 3, 16)],
        )
        assert out == {}

    def test_returns_saved_menu_grouped_by_date(self):
        fake = self._seed([
            {'client_name': 'Rippling', 'service_date': '2026-03-16',
             'menu': {'rice': 'jeera_rice', 'bread': 'naan'}},
            {'client_name': 'Rippling', 'service_date': '2026-03-17',
             'menu': {'rice': 'lemon_rice'}},
        ])
        out = HistoryManager.load_saved_plan(
            fake, 'Rippling',
            [dt.date(2026, 3, 16), dt.date(2026, 3, 17)],
        )
        assert out[dt.date(2026, 3, 16)] == {'rice': 'jeera_rice', 'bread': 'naan'}
        assert out[dt.date(2026, 3, 17)] == {'rice': 'lemon_rice'}

    def test_filters_other_clients(self):
        fake = self._seed([
            {'client_name': 'Stripe', 'service_date': '2026-03-16',
             'menu': {'rice': 'stripe_rice'}},
            {'client_name': 'Rippling', 'service_date': '2026-03-16',
             'menu': {'rice': 'rippling_rice'}},
        ])
        out = HistoryManager.load_saved_plan(
            fake, 'Rippling', [dt.date(2026, 3, 16)],
        )
        assert out[dt.date(2026, 3, 16)] == {'rice': 'rippling_rice'}

    def test_only_returns_dates_with_rows(self):
        """Caller distinguishes 'fully saved' from 'partial' by checking
        len(out) vs len(requested_dates)."""
        fake = self._seed([
            {'client_name': 'Rippling', 'service_date': '2026-03-16',
             'menu': {'rice': 'jeera_rice'}},
        ])
        out = HistoryManager.load_saved_plan(
            fake, 'Rippling',
            [dt.date(2026, 3, 16), dt.date(2026, 3, 17)],
        )
        assert list(out.keys()) == [dt.date(2026, 3, 16)]

    def test_skips_empty_menu_rows(self):
        fake = self._seed([
            {'client_name': 'Rippling', 'service_date': '2026-03-16', 'menu': {}},
        ])
        out = HistoryManager.load_saved_plan(
            fake, 'Rippling', [dt.date(2026, 3, 16)],
        )
        assert out == {}

    def test_empty_dates_is_noop(self):
        fake = self._seed([
            {'client_name': 'Rippling', 'service_date': '2026-03-16',
             'menu': {'rice': 'jeera_rice'}},
        ])
        assert HistoryManager.load_saved_plan(fake, 'Rippling', []) == {}

    def test_requires_supabase_client(self):
        with pytest.raises(ValueError):
            HistoryManager.load_saved_plan(None, 'Rippling', [dt.date(2026, 3, 16)])


class TestExplodeHistoryRows:
    """The JSONB day rows → long per-item DataFrame conversion the cooldown
    readers consume."""

    def test_explode_flattens_menu(self):
        rows = [
            {'client_name': 'Rippling', 'service_date': '2026-03-16',
             'menu': {'rice': 'jeera rice', 'bread': 'naan'}},
            {'client_name': 'Rippling', 'service_date': '2026-03-17',
             'menu': {'rice': 'lemon rice'}},
        ]
        df = HistoryManager.explode_history_rows(rows)
        assert set(df.columns) >= {'client_name', 'service_date', 'slot', 'item_base'}
        assert len(df) == 3
        assert set(df['item_base']) == {'jeera rice', 'naan', 'lemon rice'}

    def test_explode_nested_menu_flattens_all_counters(self):
        rows = [
            {'client_name': 'Rippling', 'service_date': '2026-03-16',
             'menu': {'Main': {'rice': 'jeera rice'}, 'Live': {'starter': 'tikka'}}},
        ]
        df = HistoryManager.explode_history_rows(rows)
        assert len(df) == 2
        assert set(df['item_base']) == {'jeera rice', 'tikka'}

    def test_explode_empty_is_none(self):
        assert HistoryManager.explode_history_rows([]) is None
        assert HistoryManager.explode_history_rows(None) is None

    def test_explode_round_trips_into_cooldowns(self):
        rows = [
            {'client_name': 'Rippling', 'service_date': '2026-03-01',
             'menu': {'rice': 'jeera rice'}},
        ]
        df = HistoryManager.explode_history_rows(rows)
        hm = HistoryManager().load_from_dataframes(df)
        bans = hm.banned_items_by_date([dt.date(2026, 3, 10)], cooldown_days=20)
        assert 'jeera rice' in bans[dt.date(2026, 3, 10)]
