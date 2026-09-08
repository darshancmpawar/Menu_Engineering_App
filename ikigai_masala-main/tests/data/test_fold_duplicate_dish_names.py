"""One dish, one row — `scripts/fold_duplicate_dish_names.py`.

386 rows were dropped, so the guards here are about what a fold must NOT do.
Three failure modes, in descending order of how quietly they happen:

  * **a merge keeps the misfiled row.** `propose()` ranks NAMES, and the better
    name sits on the wrong row often enough to matter — `chana_lauki` (filed
    `dal`) beats `lauki_chana` (filed `veg_dry`) alphabetically. The mechanical
    pick would have deleted the correctly-filed row and left a bottle-gourd
    sabzi in the dal pool.
  * **a re-import un-folds it.** Every dropped name is still what some client's
    sheet prints, which is what `menu_import.ALIASES` patches one name at a
    time. Asserted through `to_item`/`_existing_twin`, the functions the
    importers actually call.
  * **a site loses a dish.** The survivor has to inherit every pool token in
    the group, under the ontology's own `common` convention.

The grouping predicate itself is pinned in `test_duplicate_dish_names.py`; this
file is about applying it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / 'scripts'
sys.path.insert(0, str(_SCRIPTS))

from audit_duplicate_dish_names import (  # noqa: E402
    canonical_spelling, collect, dish_key, propose, SYNONYMS,
)
from city_list import CITIES  # noqa: E402
from fold_duplicate_dish_names import (  # noqa: E402
    _FIXES, _FORM_RENAMES, _MISFILES, _SEEDED_FROM, _for_city, apply_city,
)
from menu_import import _existing_twin, to_item, vocab_from  # noqa: E402

_ITEMS = Path(__file__).resolve().parents[2] / 'data' / 'raw' / 'city_items'


@pytest.fixture(scope='module')
def frames():
    out = {}
    for city in CITIES:
        path = _ITEMS / f'{city}.xlsx'
        if path.exists():
            df = pd.read_excel(path)
            df.columns = [c.strip() for c in df.columns]
            out[city] = df
    return out


def _names(df):
    return set(df['item'].astype(str).str.lower().str.strip())


def _row(df, item):
    hit = df[df['item'].astype(str).str.lower().str.strip() == item]
    assert not hit.empty, f'{item} is not in this city'
    return hit.iloc[0]


class TestTheFoldIsComplete:
    def test_no_city_still_carries_one_dish_under_two_names(self):
        dupes, misfiles = collect()
        assert dupes == [], dupes[:5]
        assert misfiles == [], misfiles[:5]

    def test_the_committed_report_is_current(self):
        """A stale CSV asks the client to adjudicate rows that are already
        settled."""
        import subprocess
        r = subprocess.run([sys.executable,
                            str(_SCRIPTS / 'audit_duplicate_dish_names.py'),
                            '--check'], capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr

    def test_names_and_ids_stay_unique(self, frames):
        for city, df in frames.items():
            assert df['item'].duplicated().sum() == 0, city
            assert df['item_id'].duplicated().sum() == 0, city

    def test_a_second_pass_changes_nothing(self, frames):
        """The chain has to converge; a fold that renames on every run would
        make every downstream correction script un-idempotent too."""
        for city, df in frames.items():
            _, log = apply_city(df.copy(), city)
            assert log == [], (city, log[:3])


class TestTheMisfileVerdicts:
    """Each verdict is asserted as the row that SURVIVED and the pool it lands
    in, not as a column value — a `course_type` corrected while the row stayed
    in the wrong pool is still wrong where it counts."""

    @pytest.mark.parametrize('city,item,course', [
        ('bangalore', 'tandoori_achari_aloo', 'veg_dry'),
        ('bangalore', 'chilli_baby_corn', 'veg_dry'),
        ('bangalore', 'garlic_butter_vegetables', 'veg_dry'),
        ('bangalore', 'lauki_chana', 'veg_dry'),
        ('bangalore', 'millet_curd_rice', 'rice'),
        ('bangalore', 'kadai_veg', 'veg_gravy'),
        ('bangalore', 'veg_kolhapuri', 'veg_gravy'),
        ('bangalore', 'aloo_matar_masala', 'veg_gravy'),
        ('chennai', 'sambar_vada', 'starter'),
        ('ncr', 'aloo_gobi_masala', 'veg_gravy'),
        ('ncr', 'aloo_tariwala', 'veg_gravy'),
        ('ncr', 'onion_laccha', 'salad'),
    ])
    def test_the_correctly_filed_row_is_the_one_that_survived(
            self, frames, city, item, course):
        assert _row(frames[city], item)['course_type'] == course

    @pytest.mark.parametrize('city,item', [
        ('bangalore', 'achari_tandoori_aloo'),
        ('bangalore', 'baby_corn_chilli'),
        ('bangalore', 'butter_garlic_vegetables'),
        ('bangalore', 'chana_lauki'),
        ('bangalore', 'curd_millet_rice'),
        ('bangalore', 'kadhai_veg'),
        ('bangalore', 'kolhapuri_veg'),
        ('chennai', 'vada_sambar'),
        ('ncr', 'gobi_aloo_masala'),
        ('ncr', 'tariwala_aloo'),
        ('ncr', 'laccha_onion'),
    ])
    def test_the_misfiled_row_is_gone(self, frames, city, item):
        assert item not in _names(frames[city])

    def test_hyderabad_took_the_same_verdicts_as_its_seed(self, frames):
        """Hyderabad is seeded from Bangalore, so it carries the same rows. A
        verdict applied to one city and not the other leaves the two lists
        disagreeing about what a dish IS."""
        assert _SEEDED_FROM['hyderabad'] == 'bangalore'
        for item in _MISFILES['bangalore']:
            blr, hyd = frames['bangalore'], frames['hyderabad']
            name = _MISFILES['bangalore'][item][0] or item
            assert name in _names(hyd), item
            assert (_row(hyd, name)['course_type']
                    == _row(blr, name)['course_type'])

    def test_a_raw_onion_salad_is_not_in_the_gravy_pool(self, frames):
        """The consequence, stated as what reaches a plate: a `veg_gravy`
        filing put sliced raw onion in the cell holding the day's gravy."""
        row = _row(frames['ncr'], 'onion_laccha')
        assert row['course_type'] == 'salad'
        assert str(row['key_ingredient']) == 'onion'

    def test_every_verdict_still_names_a_live_row(self, frames):
        """A verdict whose row has since been renamed away is dead code that
        reads as a live decision."""
        for city in frames:
            for item, (rename_to, reason) in _for_city(_MISFILES, city).items():
                assert (rename_to or item) in _names(frames[city]), (city, item)
                assert reason.strip(), (city, item)

    def test_the_named_column_fixes_were_applied(self, frames):
        for city in frames:
            for item, fields in _for_city(_FIXES, city).items():
                row = _row(frames[city], item)
                for col, value in fields.items():
                    assert str(row[col]) == value, (city, item, col)


class TestBothFormsSurviveWhereBothAreReal:
    """Aloo Beans is made as a dry stir-fry AND as an onion-tomato curry.
    Deleting either loses a dish a client serves, so the fix is to name the
    form — and a form word in the name is what stops the pair regrouping."""

    @pytest.mark.parametrize('city,dry,gravy', [
        ('ncr', 'achari_aloo', 'achari_aloo_gravy'),
        ('ncr', 'aloo_beans', 'aloo_beans_gravy'),
        ('ncr', 'aloo_methi', 'aloo_methi_gravy'),
        ('bangalore', 'aloo_matar_dry', 'aloo_matar'),
    ])
    def test_both_dishes_are_present_and_on_their_own_side(
            self, frames, city, dry, gravy):
        df = frames[city]
        assert _row(df, dry)['course_type'] == 'veg_dry'
        assert _row(df, gravy)['course_type'] == 'veg_gravy'

    def test_the_two_no_longer_group(self, frames):
        """Otherwise the audit reports them for a verdict on every run."""
        assert dish_key('achari_aloo') != dish_key('achari_aloo_gravy')
        assert dish_key('aloo_matar') != dish_key('aloo_matar_dry')

    def test_a_form_rename_names_the_course_it_means(self):
        """The verdict is about *the dry one*, and the name alone stopped being
        enough to identify it once the fold began minting canonical spellings:
        after `aloo_matar` became `aloo_matar_dry` the surviving gravy took the
        name `aloo_matar`, so a name-only rule could not tell "already applied"
        from "would clobber"."""
        for city, table in _FORM_RENAMES.items():
            for old, (course, new, reason) in table.items():
                assert course in ('veg_dry', 'veg_gravy'), (city, old)
                assert reason.strip()
                assert new != old

    def test_the_renamed_row_left_the_course_the_verdict_named(self, frames):
        """Not "the old name is gone" — `aloo_matar` is legitimately back in the
        list. The dry row took `aloo_matar_dry`, which freed the canonical
        spelling, and the surviving GRAVY was then minted onto it. What must
        hold is narrower: no row is left under the old (name, course) pair the
        verdict pointed at, so the rename cannot silently re-apply.
        """
        for city, df in frames.items():
            for old, (course, new, _r) in _for_city(_FORM_RENAMES, city).items():
                assert new in _names(df), (city, new)
                still = df[(df['item'].astype(str).str.lower().str.strip() == old)
                           & (df['course_type'].astype(str).str.strip()
                              .str.lower() == course)]
                assert still.empty, (city, old, course)


class TestNobodyLosesADish:
    def test_the_survivor_inherits_every_pool_token(self, frames):
        """`chilli_baby_corn` was Healthineers' and `baby_corn_chilli` Citrix's;
        the fold must not cost Citrix the dish."""
        assert {'healthineers', 'citrix'} <= {
            t.strip().lower()
            for t in str(_row(frames['bangalore'],
                              'chilli_baby_corn')['client']).split(',')}

    def test_no_row_lists_more_sites_than_the_common_threshold(self, frames):
        """The client's own rule: six or more sites making a dish means it is
        `common`. A plain union broke it — seven sites landed on one row — and
        `test_booking_import.py` asserts the same invariant over the whole
        workbook, which is what caught it."""
        from canonical_dish_spellings import COMMON_AT, _has_common_pool
        for city, df in frames.items():
            if not _has_common_pool(df):
                continue
            for value in df['client'].dropna().astype(str):
                tokens = [t for t in value.split(',') if t.strip()]
                if len(tokens) >= COMMON_AT:
                    assert any(t.strip().lower() == 'common'
                               for t in tokens), (city, value)

    def test_common_absorbs_rather_than_accumulating(self):
        """A dish in the common pool is reachable by every client, so naming
        five sites beside it says nothing.

        Asserted about the MERGE rather than about the workbook: ten Bangalore
        rows carry `common` beside a site token and pre-date this script by a
        long way, so a workbook-wide assertion would be testing somebody
        else's data. What this fold owes is that it never adds another.
        """
        from fold_duplicate_dish_names import _merge_clients
        rows = pd.DataFrame({'client': ['Citrix', 'common', 'Booking.com']})
        assert _merge_clients(rows, allow_common=True) == 'common'
        # ...and where the city has no common pool, the token list is the
        # honest record of which sites serve the dish, however long it grows.
        assert _merge_clients(rows, allow_common=False) == 'Citrix,Booking.com'

    def test_six_sites_make_a_dish_common(self):
        from canonical_dish_spellings import COMMON_AT
        from fold_duplicate_dish_names import _merge_clients
        sites = [f'Site{i}' for i in range(COMMON_AT)]
        assert _merge_clients(pd.DataFrame({'client': sites}),
                              allow_common=True) == 'common'
        assert _merge_clients(pd.DataFrame({'client': sites[:COMMON_AT - 1]}),
                              allow_common=True) != 'common'

    def test_a_site_token_is_never_duplicated_by_the_union(self):
        from fold_duplicate_dish_names import _merge_clients
        rows = pd.DataFrame({'client': ['Citrix,Stryker', 'stryker', 'Citrix']})
        assert _merge_clients(rows, allow_common=True) == 'Citrix,Stryker'

    def test_ncr_was_not_given_a_common_token_it_has_no_pool_for(self, frames):
        """NCR tags all ~1,500 rows to one of eight sites. Promoting there
        writes a token naming no pool that exists."""
        assert 'common' not in {
            t.strip().lower() for value in frames['ncr']['client'].dropna()
            .astype(str) for t in value.split(',')}

    def test_a_value_only_the_dropped_row_carried_is_kept(self, frames):
        """`tandoori_achari_aloo` survived with a blank `key_ingredient` while
        the row folded into it said `potato`. The rows are the same dish, so
        that was data the fold had no quarrel with."""
        assert str(_row(frames['bangalore'],
                        'tandoori_achari_aloo')['key_ingredient']) == 'potato'


class TestTheFoldSurvivesTheNextImport:
    """Every dropped name is still what some client's sheet PRINTS. Asserted
    through the functions the importers call, not through a table — `to_item`
    already applies `ALIASES`, so asserting on the dict would pass while the
    resolution was broken."""

    @pytest.fixture(scope='class')
    def blr(self):
        df = pd.read_excel(_ITEMS / 'bangalore.xlsx')
        df.columns = [c.strip() for c in df.columns]
        return df

    @pytest.mark.parametrize('printed,expected', [
        ('Dum Aloo', 'aloo_dum'),
        ('Murgh Nizami', 'chicken_nizami'),
        ('Mutter Paneer', 'matar_paneer'),
        ('Kadhai Paneer', 'kadai_paneer'),
        ('Bhindi Achari', 'achari_bhindi'),
        ('Palak Murgh', 'palak_chicken'),
    ])
    def test_a_printed_variant_resolves_to_the_surviving_row(
            self, blr, printed, expected):
        names = sorted(_names(blr))
        assert expected in names, expected
        candidate = to_item(printed)
        if candidate == expected:
            return                            # a spelling rule already had it
        assert _existing_twin(candidate, names, vocab_from(blr)) == expected

    def test_a_name_already_in_the_ontology_is_left_alone(self, blr):
        """`_existing_twin` answers "which dish is this a spelling OF"; for a
        dish that IS in the list the answer is none, or an importer would fold
        a real row onto a look-alike."""
        names = sorted(_names(blr))
        assert _existing_twin('aloo_dum', names, vocab_from(blr)) is None

    def test_a_form_difference_never_resolves_across_it(self, blr):
        """The distinction the whole audit turns on: a dry and a gravy of the
        same ingredients are two dishes."""
        names = ['chilli_paneer_dry', 'chilli_paneer_gravy']
        from menu_import import _same_dish_by_meaning
        assert _same_dish_by_meaning('paneer_chilli_gravy',
                                     names) == 'chilli_paneer_gravy'
        assert _same_dish_by_meaning('paneer_chilli_dry',
                                     names) == 'chilli_paneer_dry'

    def test_an_ambiguous_key_is_refused_rather_than_guessed(self):
        """Two surviving rows sharing a key is exactly the state the audit
        reports for a verdict. Guessing between them imports a client's gravy
        onto their dry row."""
        from menu_import import _same_dish_by_meaning
        assert _same_dish_by_meaning('aloo_matar',
                                     ['matar_aloo', 'aloo_mutter']) is None

    def test_a_name_of_nothing_but_form_words_resolves_to_nothing(self):
        """`dish_key('curry')` has an empty core, which would otherwise match
        every other coreless name in the list."""
        from menu_import import _same_dish_by_meaning
        assert _same_dish_by_meaning('curry', ['masala', 'gravy']) is None

    def test_a_genuinely_new_dish_is_still_new(self, blr):
        from menu_import import _same_dish_by_meaning
        assert _same_dish_by_meaning('kuttu_ka_dosa_with_samak',
                                     sorted(_names(blr))) is None


class TestTheProposedNameIsNeverAFoldedAwaySpelling:
    def test_the_canonical_alternative_wins_when_the_group_holds_one(self):
        assert propose(['kadai_chicken', 'kadhai_chicken']) == 'kadai_chicken'
        assert propose(['harayali_egg_curry',
                        'hariyali_egg_curry']) == 'hariyali_egg_curry'
        assert propose(['mutter_paneer', 'matar_paneer']) == 'matar_paneer'

    def test_the_winner_is_spelled_out_when_no_candidate_is_clean(self):
        """Otherwise the ranking is just picking the least-bad of five and the
        surviving row keeps a spelling the project standardised away."""
        assert propose(['murgh_nizami', 'nizami_murgh']) == 'chicken_nizami'
        assert propose(['chicken_rezalla', 'murgh_razeela',
                        'murgh_razala']) == 'chicken_razala'

    def test_phrases_do_not_decide_spellings(self):
        """`PHRASES` targets are artificial grouping keys — `hotsour` is not a
        word — so reading them here picked `paneer_dopyaza` over
        `paneer_do_pyaza` and `chicken_kalimirch` over `chicken_kali_mirch`."""
        assert propose(['paneer_do_pyaza',
                        'paneer_dopyaza']) == 'paneer_do_pyaza'
        assert propose(['chicken_kali_mirch',
                        'chicken_kalimirch']) == 'chicken_kali_mirch'
        assert propose(['egg_do_pyaz', 'egg_do_pyaza']) == 'egg_do_pyaza'

    def test_no_surviving_row_carries_a_folded_away_word(self, frames):
        """The point of the gate, over the whole workbook rather than per
        group: a fold that elects `kadhai` undoes a committed correction one
        row at a time.

        Only where the group HAD a clean alternative, which is what the fold
        promises — `aloo_gobi_mutter | gobi_aloo_mutter` legitimately kept
        `mutter` until `mutter -> matar` entered SYNONYMS, and the wider
        vocabulary fold belongs to `canonical_dish_spellings.py`.
        """
        for city, df in frames.items():
            for name in _names(df):
                clean = canonical_spelling(name)
                if clean != name:
                    assert clean not in _names(df), (city, name, clean)

    def test_the_ranking_is_deterministic(self):
        names = ['chicken_bhuna_masala', 'bhuna_murgh_masala',
                 'bhuna_chicken_masala']
        assert propose(names) == propose(list(reversed(names)))

    def test_mutter_and_matar_are_one_word(self):
        """The split left NCR holding four rows of methi malai peas."""
        assert SYNONYMS['mutter'] == 'matar'
        assert dish_key('methi_malai_mutter') == dish_key('matar_methi_malai')
