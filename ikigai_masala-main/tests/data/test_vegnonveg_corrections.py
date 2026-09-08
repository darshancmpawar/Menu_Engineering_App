"""The vegetarian line, in both directions.

This is the one ontology error whose consequence is outside the software, so
the assertions are about what reaches a plate rather than about column values:

  * a vegetarian dish marked non-veg is dropped from its own pool by
    `_nonveg_mask` and, being `nonveg_main`, is offered as the day's meat dish;
  * a meat dish marked vegetarian stays in the veg pools and is plated to
    someone who asked not to be served meat.

Both plate. Neither raises. So each correction is pinned twice — the row's
values, and the POOL the row ends up in — because a course_type fixed while a
flag was left set is still on the wrong side of the line.
"""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.city_list import CITIES
from scripts.vegnonveg_corrections import (
    NEEDS_CLIENT_DECISION, NONVEG_CORRECTIONS, NONVEG_FLAGS, PROTEIN_ONLY,
    VEG_CORRECTIONS, apply_city,
)
from src.constants import NONVEG_PROTEINS, NONVEG_SLOTS
from src.preprocessor.pool_builder import _nonveg_mask


def _norm(v) -> str:
    return str(v if v is not None else '').strip().lower()


@pytest.fixture(scope='module')
def cities(project_root_path):
    out = {}
    for city in CITIES:
        path = project_root_path / 'data' / 'raw' / 'city_items' / f'{city}.xlsx'
        df = pd.read_excel(path)
        df.columns = [c.strip() for c in df.columns]
        out[city] = df
    return out


def _row(df, item):
    hit = df[df['item'].map(_norm) == item]
    assert len(hit) == 1, f'{item!r} matched {len(hit)} rows'
    return hit.iloc[0]


class TestTheVegetarianDishesAreBackInVegPools:
    def test_every_corrected_row_is_readable_as_vegetarian(self, cities):
        """`_nonveg_mask` is the function that decides, so ask it rather than
        re-reading the columns it reads."""
        for city, items in VEG_CORRECTIONS.items():
            df = cities[city]
            for item in items:
                r = _row(df, item)
                masked = bool(_nonveg_mask(df.loc[[r.name]]).iloc[0])
                assert not masked, f'{city}/{item} still reads non-veg'

    def test_none_of_them_is_left_in_a_nonveg_slot(self, cities):
        for city, items in VEG_CORRECTIONS.items():
            df = cities[city]
            for item in items:
                assert _norm(_row(df, item)['course_type']) not in NONVEG_SLOTS

    def test_every_nonveg_form_flag_is_cleared(self, cities):
        """A course_type fixed while `is_nonveg_gravy` stayed set leaves the row
        eligible for `nonveg_main_daily_pair`'s gravy component — corrected on
        paper and still plated as the meat dish."""
        for city, items in VEG_CORRECTIONS.items():
            df = cities[city]
            for item in items:
                r = _row(df, item)
                on = [f for f in NONVEG_FLAGS if f in df.columns
                      and pd.to_numeric(pd.Series([r[f]]), errors='coerce').fillna(0)[0] == 1]
                assert not on, f'{city}/{item} still carries {on}'

    def test_the_soya_keema_family_agrees_with_itself(self, cities):
        """The defect was a family disagreeing: `soya_keema_mutter` was `soy`
        and `soya_matar_keema` was `mutton`, the same dish twice. Whatever the
        value is, every row of the family has to share it."""
        df = cities['ncr']
        fam = df[df['item'].map(_norm).str.contains('soya_keema|soya_matar_keema|nutri_keema|nutree_keema')]
        prots = {_norm(p) for p in fam['primary_protein']}
        assert prots == {'soy'}, prots

    def test_the_dish_is_still_described(self, cities):
        """A correction that blanked the row would trade a wrong dish for an
        undescribable one — `key_ingredient` is read by attribute_grouping and
        ingredient_ban_rule."""
        for city, items in VEG_CORRECTIONS.items():
            df = cities[city]
            for item in items:
                assert _norm(_row(df, item)['key_ingredient'])


class TestTheMeatDishesAreOutOfVegPools:
    def test_every_corrected_row_reads_non_veg(self, cities):
        for city, items in NONVEG_CORRECTIONS.items():
            df = cities[city]
            for item in items:
                r = _row(df, item)
                assert bool(_nonveg_mask(df.loc[[r.name]]).iloc[0]), \
                    f'{city}/{item} still reads vegetarian'
                assert _norm(r['course_type']) in NONVEG_SLOTS

    def test_no_veg_side_form_flag_survives(self, cities):
        """`chilli_chiken` carried `is_chinese_veg_gravy`, so it was not merely
        in the veg pool — it was eligible for a themed Chinese VEG gravy cell.
        Moving the course without clearing that leaves the hole open."""
        for city, items in NONVEG_CORRECTIONS.items():
            df = cities[city]
            for item in items:
                r = _row(df, item)
                for flag in ('is_chinese_veg_gravy', 'is_paneer_gravy', 'is_paneer_fry'):
                    if flag in df.columns:
                        val = pd.to_numeric(pd.Series([r[flag]]), errors='coerce').fillna(0)[0]
                        assert val == 0, f'{city}/{item} still carries {flag}'

    def test_each_has_a_form_flag_so_it_can_actually_be_placed(self, cities):
        """A non-veg row with no form flag is never chosen by
        `nonveg_main_daily_pair` — it would sit in the pool unservable, which is
        the defect `nonveg_structural_flags.py` exists for."""
        forms = ('is_nonveg_dry', 'is_nonveg_gravy', 'is_nonveg_biryani')
        for city, items in NONVEG_CORRECTIONS.items():
            df = cities[city]
            for item in items:
                r = _row(df, item)
                on = [f for f in forms if f in df.columns
                      and pd.to_numeric(pd.Series([r[f]]), errors='coerce').fillna(0)[0] == 1]
                assert on, f'{city}/{item} has no form flag'


class TestTheProteinOnlyFixes:
    def test_the_values_are_what_the_dish_name_means(self, cities):
        for city, items in PROTEIN_ONLY.items():
            df = cities[city]
            for item, (prot, _on, _off) in items.items():
                assert _norm(_row(df, item)['primary_protein']) == prot

    def test_an_egg_dish_no_longer_satisfies_a_chicken_rule(self, cities):
        """`kodi guddu` is Telugu for chicken EGG, and both rows carried
        `is_north_chicken_gravy` — which is what let ICON Chn's "a chicken gravy
        on Tuesday" come back as an egg kurma."""
        for city in ('bangalore', 'hyderabad'):
            df = cities[city]
            for item in ('kodi_guddu_masala', 'kothimeera_kodiguddu'):
                r = _row(df, item)
                assert pd.to_numeric(pd.Series([r['is_egg_dish']]),
                                     errors='coerce').fillna(0)[0] == 1
                assert pd.to_numeric(pd.Series([r['is_north_chicken_gravy']]),
                                     errors='coerce').fillna(0)[0] == 0

    def test_the_chicken_curry_next_door_is_untouched(self, cities):
        """`kodi kura` IS chicken curry — only `kodi guddu` is egg. Correcting
        by the word "kodi" would have taken both."""
        r = _row(cities['hyderabad'], 'kothmeera_kodikura')
        assert _norm(r['primary_protein']) == 'chicken'


class TestWhatWasDeliberatelyNotChanged:
    def test_keema_matar_is_left_non_veg(self, cities):
        """The trap that makes a name rule wrong in the other direction: Keema
        Matar is the MEAT dish — the peas are added to the mince, not
        substituted for it. A rule keyed on `matar` flips exactly this one."""
        r = _row(cities['ncr'], 'mutter_keema')
        assert _norm(r['primary_protein']) == 'mutton'
        assert _norm(r['course_type']) in NONVEG_SLOTS

    def test_the_open_questions_are_reported(self, project_root_path):
        report = project_root_path / 'docs' / 'vegnonveg_to_confirm.csv'
        assert report.exists(), 'the client questions were not written'
        text = report.read_text(encoding='utf-8')
        for item, *_ in NEEDS_CLIENT_DECISION:
            assert item.split(' ')[0] in text

    def test_every_reported_row_still_exists(self, cities):
        """A question about a row since renamed away is noise the reader has to
        re-derive. Composite entries name a family, so only single ones check."""
        for item, city_csv, _state, _q in NEEDS_CLIENT_DECISION:
            if any(c in item for c in ('/', '+', '...')):
                continue
            for city in city_csv.split(','):
                df = cities[city.strip()]
                assert (df['item'].map(_norm) == item).any(), f'{city}/{item} gone'


class TestTheGuardCannotPassVacuously:
    def test_a_planted_veg_dish_marked_non_veg_is_corrected(self, cities):
        df = cities['ncr'].copy()
        i = df.index[df['item'].map(_norm) == 'bhuna_soya_keema'][0]
        df.at[i, 'primary_protein'] = 'mutton'
        df.at[i, 'course_type'] = 'nonveg_main'
        df.at[i, 'is_nonveg_gravy'] = 1
        out, changes = apply_city(df, 'ncr')
        r = out.loc[i]
        assert _norm(r['primary_protein']) == 'soy'
        assert _norm(r['course_type']) == 'veg_dry'
        assert any('bhuna_soya_keema' in c for c in changes)

    def test_a_planted_meat_dish_marked_veg_is_corrected(self, cities):
        df = cities['ncr'].copy()
        i = df.index[df['item'].map(_norm) == 'tandoori_chcien'][0]
        df.at[i, 'primary_protein'] = ''
        df.at[i, 'course_type'] = 'veg_gravy'
        out, _ = apply_city(df, 'ncr')
        assert _norm(out.loc[i, 'primary_protein']) == 'chicken'
        assert _norm(out.loc[i, 'course_type']) == 'nonveg_main'

    def test_a_second_pass_changes_nothing(self, cities):
        for city in CITIES:
            once, first = apply_city(cities[city], city)
            twice, second = apply_city(once, city)
            assert not second or first == second
            pd.testing.assert_frame_equal(once, twice)


class TestNothingElseIsStrandedOnTheWrongSide:
    def test_no_row_is_unservable(self, cities):
        """The class both corrections could create: marked non-veg by
        `_nonveg_mask` while filed outside a non-veg slot, so it is dropped from
        its own pool and never joins `nonveg_main`. It cannot be served at all.
        """
        for city, df in cities.items():
            masked = _nonveg_mask(df)
            slot = df['course_type'].map(_norm).isin(NONVEG_SLOTS)
            stranded = df.loc[masked & ~slot, 'item'].tolist()
            assert not stranded, f'{city}: {stranded}'

    def test_no_nonveg_protein_outside_a_nonveg_slot(self, cities):
        for city, df in cities.items():
            bad = df.loc[df['primary_protein'].map(_norm).isin(NONVEG_PROTEINS)
                         & ~df['course_type'].map(_norm).isin(NONVEG_SLOTS), 'item']
            assert not len(bad), f'{city}: {bad.tolist()}'

    def test_a_keema_row_is_meat_only_when_its_name_says_so(self, cities):
        """The family that started this, as an invariant rather than a list.

        `keema` means mince and says nothing about what is minced, so the
        evidence has to come from the rest of the name: a meat word makes it
        meat, a soya/vegetable word makes it vegetarian. Stated this way the
        check keeps working when a city gains a keema — an allow-list of the
        rows that happen to exist today would not, and the first thing it did
        was flag three Bangalore rows (`anda_keema_ghotala`, `egg_kheema_masala`,
        `chicken_keema_mutter`) that are perfectly correct.
        """
        MEAT = ('chicken', 'mutton', 'lamb', 'gosht', 'anda', 'egg', 'murg',
                'fish', 'prawn', 'keema_pav')
        # `mutter_keema` is the one row whose name settles nothing: Keema Matar
        # is the MEAT dish, so it stays non-veg pending the client's word.
        UNSETTLED = {'mutter_keema'}
        for city, df in cities.items():
            rows = df[df['item'].map(_norm).str.contains('keema|kheema')]
            if not len(rows):
                continue
            meat = rows[_nonveg_mask(rows)]['item'].map(_norm)
            unexplained = [m for m in meat
                           if not any(w in m for w in MEAT) and m not in UNSETTLED]
            assert not unexplained, (
                f'{city}: keema rows marked meat with nothing in the name to '
                f'support it: {unexplained}')

    def test_a_soya_or_vegetable_keema_is_never_meat(self, cities):
        """The other half, and the one that was broken: eleven NCR rows."""
        VEG = ('soya', 'soy', 'nutri', 'nutree', 'gobi', 'veg_keema',
               'paneer', 'mushroom')
        for city, df in cities.items():
            rows = df[df['item'].map(_norm).str.contains('keema|kheema')]
            if not len(rows):
                continue
            veg_named = rows[rows['item'].map(_norm).apply(
                lambda s: any(w in s for w in VEG))]
            wrong = veg_named[_nonveg_mask(veg_named)]['item'].tolist()
            assert not wrong, f'{city}: vegetarian keema marked meat: {wrong}'
