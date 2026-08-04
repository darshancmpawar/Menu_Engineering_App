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
