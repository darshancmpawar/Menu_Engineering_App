"""A dish must sit in its own category, not one that merely resembles it.

`course_type` decides which slot pool a dish lands in, so a misfiled row becomes
servable in the wrong position on the plate. Two got through everything —
every rule, every diagnostic, the whole suite — and only surfaced when a generated
menu was read dish by dish:

  * `semiya_pal_payasam` filed `veg_gravy`: a dessert served as one of a day's two
    gravies (ToastTab CHN, Tuesday);
  * `moong_dal_dosa` filed `dal`: 37 other dosas are `bread`, so this was the one
    row that could serve a dosa as a client's dal.

Nothing in the engine knows what a dish *is*, only what its columns say, so no rule
could have caught either. This test is the substitute: it compares each dish's name
against its filing and fails on anything not explicitly adjudicated.
"""

from __future__ import annotations

import os

import pandas as pd
import pytest

from scripts.audit_course_types import (
    ADJUDICATED,
    CITY_ITEMS,
    LEGITIMATE_PAIRS,
    NAME_SIGNALS,
    audit_city,
)
from scripts.course_type_corrections import CORRECTIONS, apply_corrections

CITIES = ['bangalore', 'chennai', 'pune']


def _read(city):
    return pd.read_excel(os.path.join(CITY_ITEMS, f'{city}.xlsx'))


class TestNoDishSitsInSomebodyElsesCategory:
    @pytest.mark.parametrize('city', CITIES)
    def test_no_unadjudicated_mismatch(self, city):
        bad, _ok = audit_city(_read(city), city)
        assert not bad, (
            f'{city}: {bad}. Either the row is misfiled — add it to '
            f'scripts/course_type_corrections.py — or it is correct, in which '
            f'case add it to ADJUDICATED in scripts/audit_course_types.py WITH '
            f'THE REASON.')

    @pytest.mark.parametrize('city', CITIES)
    def test_the_audit_is_not_vacuous(self, city):
        """It must be finding and allowing things. If the token matcher broke,
        every city would report zero mismatches and the test above would pass for
        entirely the wrong reason."""
        _bad, ok = audit_city(_read(city), city)
        assert ok, f'{city}: audit matched nothing at all — matcher is broken'

    def test_a_planted_misfile_is_caught(self):
        """The guard on the guard: prove a real misfile fails rather than trusting
        that it would."""
        df = pd.DataFrame({'item': ['semiya_payasam'], 'course_type': ['veg_gravy']})
        bad, _ok = audit_city(df, 'chennai')
        assert bad == [('semiya_payasam', 'veg_gravy', 'dessert')]


class TestTheTwoRealMisfilesStayFixed:
    """Re-importing a workbook through the normaliser drops hand-applied fixes, so
    these assert the corrected state directly rather than trusting the script ran."""

    def test_payasams_are_desserts(self):
        d = _read('chennai').set_index('item')
        for item in ('semiya_pal_payasam', 'millet_payasam'):
            assert d.at[item, 'course_type'] == 'dessert', item

    def test_sweet_pongal_is_a_dessert_not_rice(self):
        d = _read('chennai').set_index('item')
        for item in ('kalkandu_pongal', 'mapillai_samba_sweet_pongal'):
            assert d.at[item, 'course_type'] == 'dessert', item

    def test_the_dal_dosa_is_a_bread(self):
        d = _read('bangalore').set_index('item')
        assert d.at['moong_dal_dosa', 'course_type'] == 'bread'
        assert 'dal' not in str(d.at['moong_dal_dosa', 'sub_category'])

    @pytest.mark.parametrize('city', ['bangalore', 'chennai'])
    def test_tomato_thokku_is_a_gravy(self, city):
        """Filed `accompaniment` so it could never reach the veg-gravy slot, yet
        ToastTab's Friday sample serves it there; the client confirmed it is a
        gravy (D2)."""
        d = _read(city).set_index('item')
        assert d.at['tomato_thokku', 'course_type'] == 'veg_gravy'

    def test_it_is_the_only_dosa_that_was_wrong(self):
        """Stated as a property rather than a one-off: a dish that IS a dosa is a
        bread.

        Matched on the trailing token, not on 'contains dosa' — `dosa_chutney` is a
        chutney *for* dosa and is correctly an accompaniment. The first version of
        this test asserted every row containing 'dosa' was bread and failed on
        exactly that, which is the same over-broad matching the auditor avoids.
        """
        d = _read('bangalore')
        names = d['item'].astype(str).str.strip()
        is_a_dosa = names.str.split('_').str[-1].isin({'dosa', 'dosai'})
        offenders = d[is_a_dosa & (d['course_type'] != 'bread')]
        assert offenders.empty, offenders[['item', 'course_type']].to_dict('records')

    @pytest.mark.parametrize('city', sorted(CORRECTIONS))
    def test_rerunning_the_corrections_changes_nothing(self, city):
        before = _read(city)
        _after, changes = apply_corrections(before, city)
        assert not changes, changes


class TestTheAdjudicationsAreHonest:
    def test_every_adjudicated_row_still_exists(self):
        """A stale entry silently widens the allow-list for a dish that was renamed
        or removed."""
        stale = []
        for (city, item) in ADJUDICATED:
            if item not in set(_read(city)['item'].astype(str).str.strip()):
                stale.append((city, item))
        assert not stale, f'adjudicated rows no longer in the data: {stale}'

    def test_every_adjudication_carries_a_reason(self):
        blank = [k for k, v in ADJUDICATED.items() if not str(v).strip()]
        assert not blank, blank

    def test_signals_and_pairs_are_self_consistent(self):
        """Every course named in LEGITIMATE_PAIRS' second slot must be a course the
        matcher can actually imply, or the pair silences nothing."""
        implied = {p[1] for p in LEGITIMATE_PAIRS}
        assert implied <= set(NAME_SIGNALS), implied - set(NAME_SIGNALS)


class TestUnservableRowsAreCaughtStructurally:
    """A row can be filed in a plausible category and still be impossible to serve.

    `PoolBuilder._nonveg_mask` drops any non-veg `primary_protein` from every slot
    except `nonveg_main`. So a non-veg protein on a row whose `course_type` is
    something else leaves its own pool and joins nothing. No name check finds this —
    both examples had perfectly descriptive names — so the check is structural.
    """

    @pytest.mark.parametrize('city', CITIES)
    def test_no_city_has_an_unservable_row(self, city):
        from scripts.audit_course_types import unservable_rows
        assert unservable_rows(_read(city)) == []

    def test_the_check_catches_a_planted_orphan(self):
        from scripts.audit_course_types import unservable_rows
        df = pd.DataFrame({'item': ['egg_pulao'], 'course_type': ['rice'],
                           'primary_protein': ['egg']})
        assert unservable_rows(df) == [('egg_pulao', 'rice', 'egg')]

    def test_a_nonveg_row_in_nonveg_main_is_fine(self):
        from scripts.audit_course_types import unservable_rows
        df = pd.DataFrame({'item': ['chicken_biryani'],
                           'course_type': ['nonveg_main'],
                           'primary_protein': ['chicken']})
        assert unservable_rows(df) == []

    def test_egg_fried_rice_is_now_reachable(self):
        """It was course_type `rice` + protein `egg`, so it was dropped from the
        rice pool and never entered nonveg_main. Now it can actually be served."""
        from api.config import city_excel_path, city_required_slots
        from src.preprocessor.data_cleanser import DataCleanser
        from src.preprocessor.excel_reader import ExcelReader
        from src.preprocessor.pool_builder import PoolBuilder
        df = DataCleanser(ExcelReader(city_excel_path('Bangalore')).read()).clean()
        pools = PoolBuilder().build_pools(
            df, required_slots=city_required_slots('Bangalore'))
        assert 'egg_fried_rice' in set(pools['nonveg_main']['item'])

    def test_urandai_kuzhambu_stayed_vegetarian(self):
        """The fix ran the other way: the dish was correctly a veg_gravy and its
        PROTEIN was wrong. Moving it to nonveg_main would have made a
        lentil-dumpling gravy non-veg to silence the checker."""
        d = _read('chennai').set_index('item')
        prot = str(d.at['urandai_kuzhambu', 'primary_protein']).strip().lower()
        assert prot in ('', 'nan', 'none'), prot
        assert d.at['urandai_kuzhambu', 'course_type'] == 'veg_gravy'


class TestDrinksAreNotGravies:
    def test_plain_buttermilks_are_welcome_drinks(self):
        d = _read('bangalore').set_index('item')
        for item in ('butter_milk', 'masala_butter_milk', 'boondi_butter_milk'):
            assert d.at[item, 'course_type'] == 'welcome_drink', item

    def test_majjige_huli_is_still_a_gravy(self):
        """The counter-case that keeps the fix honest: majjige huli IS a buttermilk
        CURRY. Had the token list keyed on `majjige` instead of `buttermilk`, these
        three would have been dragged into welcome_drink."""
        d = _read('bangalore').set_index('item')
        for item in ('majjige_huli', 'bendekai_majjige_huli', 'sorekai_majjige_huli'):
            assert d.at[item, 'course_type'] == 'veg_gravy', item


class TestTheThreeCitySheetsAgree:
    """What the user asked to have verified, as an assertion rather than a report."""

    def test_all_three_have_the_same_columns_in_the_same_order(self):
        ref = list(_read('bangalore').columns)
        for city in CITIES[1:]:
            assert list(_read(city).columns) == ref, city
        assert len(ref) == 135

    def test_sub_categories_are_mostly_shared_with_the_master(self):
        """Not identical — a city with dishes the master lacks legitimately needs
        new values. Unlike columns, sub_category is free text per row, not an enum,
        so divergence is allowed; it is the RATE that matters."""
        def subs(city):
            s = _read(city)['sub_category'].astype(str).str.strip().str.lower()
            return set(s) - {'', 'nan', 'none'}
        master = subs('bangalore')
        assert subs('pune') <= master, sorted(subs('pune') - master)
        chennai_only = subs('chennai') - master
        # Only the seafood + sweet-pongal buckets this work introduced, which
        # Bangalore cannot share because it has zero fish and no sweet pongal.
        assert chennai_only == {
            'fish_chinese_dry', 'fish_south_coastal', 'fish_spicy_fry',
            'sweet_pongal',
        }, sorted(chennai_only)


class TestACurdRiceBelongsToTheCurdRiceStation:
    """A dish appears in the slot that IS its category, not in every slot whose
    column it happens to satisfy.

    The `curd_rice` station is flag-driven (`is_curd_rice`) while a curd rice's
    `course_type` is `rice`, so every one sat in BOTH pools. A counter running
    `rice` and `curd_rice` together could therefore serve the SAME dish twice on
    one day, and ToastTab CHN did: `dry_fruits_curd_rice` came back as both
    Tuesday's flavoured rice and its curd rice.

    `unique_items` could not prevent it. The curd-rice staple declaration
    deliberately exempts the dish so it may recur across days, and that exemption
    also permitted the same-day pair.
    """

    @pytest.fixture(scope='class')
    def pools(self):
        from api.config import city_excel_path, city_required_slots
        from src.preprocessor.data_cleanser import DataCleanser
        from src.preprocessor.excel_reader import ExcelReader
        from src.preprocessor.pool_builder import PoolBuilder
        out = {}
        for city in ('Bangalore', 'Chennai', 'Pune'):
            df = DataCleanser(ExcelReader(city_excel_path(city)).read()).clean()
            out[city] = PoolBuilder().build_pools(
                df, required_slots=city_required_slots(city))
        return out

    @pytest.mark.parametrize('city', ['Bangalore', 'Chennai', 'Pune'])
    def test_the_two_pools_are_disjoint(self, pools, city):
        p = pools[city]
        overlap = set(p['rice']['item']) & set(p['curd_rice']['item'])
        assert not overlap, sorted(overlap)

    def test_the_curd_rice_station_still_has_its_dishes(self, pools):
        """The exclusion must remove them from `rice`, not from `curd_rice` — that
        would starve the station instead of fixing the duplicate."""
        assert len(pools['Bangalore']['curd_rice']) == 13
        assert len(pools['Chennai']['curd_rice']) == 2

    def test_the_rice_pool_is_not_meaningfully_smaller(self, pools):
        """13 of 531 in Bangalore, 2 of 38 in Chennai — no starvation risk for a
        client that runs `rice` without a curd-rice station."""
        assert len(pools['Bangalore']['rice']) > 500
        assert len(pools['Chennai']['rice']) >= 36
