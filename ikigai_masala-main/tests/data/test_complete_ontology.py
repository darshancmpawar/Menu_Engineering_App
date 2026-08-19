"""The ontology completion pass: what it fills, and what it refuses to fill.

`complete_ontology.py` closed the hole the six client menu imports left — 1,773
rows carrying no `is_*` flag at all, invisible to every flag-driven rule. It does
that by learning from the rows the ontology already classifies rather than by
hand-writing a rule per column across 112 flags, so these tests pin the two
things that can go wrong with a learned fill:

* it stops being **true** — a course mirror that no longer holds, an implication
  that starts contradicting itself, a fill that lands outside the column's scope;
* it stops being **safe** — the premium clause the client's data disagrees with
  getting applied after all, or a second run finding more work to do (the whole
  correction-script convention here is that re-running changes nothing).
"""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.complete_ontology import (
    COLUMN_MIRRORS,
    COLUMN_SCOPE,
    COURSE_MIRRORS,
    MIN_EXCLUSIVE_SUPPORT,
    MIXED_VEG_CATCHALL,
    PREMIUM_FLAG_BY_COURSE,
    TOKEN_STOPWORDS,
    _classified,
    _norm,
    _numeric_flags,
    _resolve_conflicts,
    apply,
    flagless,
    is_premium,
    learn_all,
    learn_exclusive_pairs,
    learn_flag_tokens,
    load,
)

CITIES = ('bangalore', 'pune', 'chennai', 'ncr')

#: Columns a crafted row needs before `apply` will look at it.
_SKELETON = ('item', 'course_type', 'cuisine_family', 'item_color',
             'primary_protein') + tuple(COLUMN_SCOPE)


def _synthetic(rows):
    """A minimal frame in the ontology's shape, for testing what `apply` writes.

    Real workbooks answer "is the shipped data consistent"; this answers "does
    this code do the right thing", which is the question a regression needs.
    """
    flags = [f for f in COURSE_MIRRORS] + \
            [f for flags in PREMIUM_FLAG_BY_COURSE.values() for f in flags] + \
            list(COLUMN_MIRRORS) + ['is_rule_ready', 'is_dosa', 'is_paratha']
    frame = pd.DataFrame(rows)
    for column in _SKELETON:
        if column not in frame.columns:
            frame[column] = None
    for flag in dict.fromkeys(flags):
        if flag not in frame.columns:
            frame[flag] = 0
    return frame


@pytest.fixture(scope='module')
def frames():
    return load()


@pytest.fixture(scope='module')
def everything(frames):
    return pd.concat(frames.values(), ignore_index=True)


@pytest.fixture(scope='module')
def learned(frames):
    return learn_all(frames)


class TestTheMirrorsStillHold:
    """A mirror is a claim about the data, so re-derive it instead of trusting it."""

    @pytest.mark.parametrize('flag', sorted(COURSE_MIRRORS))
    def test_every_row_of_the_course_carries_the_flag(self, everything, flag):
        courses, _ = COURSE_MIRRORS[flag]
        num = _numeric_flags(everything)
        course = everything['course_type'].astype(str).str.strip().str.lower()
        belongs = course.isin(courses)
        missing = everything[belongs & (num[flag] != 1)]
        assert missing.empty, sorted(missing['item'].head(10))

    @pytest.mark.parametrize('flag', sorted(COURSE_MIRRORS))
    def test_no_row_outside_the_course_carries_it(self, everything, flag):
        """The direction that catches re-file residue.

        `moong_dal_dosa` moved from `dal` to `bread` and `jodhpuri_pulao` out of
        `bread`, but the flag the old course had put there stayed — so a dal rule
        could still pick the dosa.
        """
        courses, _ = COURSE_MIRRORS[flag]
        num = _numeric_flags(everything)
        course = everything['course_type'].astype(str).str.strip().str.lower()
        stray = everything[~course.isin(courses) & (num[flag] == 1)]
        assert stray.empty, sorted(zip(stray['item'], stray['course_type']))[:10]

    @pytest.mark.parametrize('flag', sorted(COLUMN_MIRRORS))
    def test_column_mirrors_agree_with_their_column(self, everything, flag):
        column, value, _ = COLUMN_MIRRORS[flag]
        num = _numeric_flags(everything)
        holds = everything[column].astype(str).str.strip().str.lower() == value
        assert everything[holds & (num[flag] != 1)].empty

    def test_the_recorded_coverage_is_not_stale(self, everything):
        """The number in the table is evidence; it has to still be true."""
        classified = _classified(everything)
        course = classified['course_type'].astype(str).str.strip().str.lower()
        num = _numeric_flags(classified)
        for flag, (courses, recorded) in COURSE_MIRRORS.items():
            pool = num[course.isin(courses).values]
            assert len(pool) > 20, flag
            assert (pool[flag] == 1).mean() >= recorded - 0.001, flag


class TestNothingContradictsItself:

    def test_no_row_holds_two_mutually_exclusive_flags(self, frames, everything):
        """A dish has one form.

        The two inference channels are existential — every matching word and
        attribute fires — so `paneer_masala_dosa` drew `is_dosa` from the word
        and `is_paratha` from `key_ingredient == paneer`, every classified paneer
        bread in the ontology being a paneer paratha.
        """
        classified = _classified(everything)
        flags = [c for c in everything.columns if c.startswith('is_')]
        exclusive = learn_exclusive_pairs(classified, flags)
        assert exclusive, 'no exclusive pairs learned at all'
        violations = []
        for city, d in frames.items():
            num = _numeric_flags(d)
            course = d['course_type'].astype(str).str.strip().str.lower()
            for name, a, b in exclusive:
                hit = (course == name) & (num[a] == 1) & (num[b] == 1)
                violations += [(city, i, a, b) for i in d.loc[hit, 'item']]
        assert not violations, violations[:10]

    def test_exclusive_pairs_are_stored_sorted(self, everything):
        """Regression: they were stored in column order and looked up sorted, so
        every pair was a silent miss and the resolution never fired."""
        classified = _classified(everything)
        flags = [c for c in everything.columns if c.startswith('is_')]
        for _, a, b in learn_exclusive_pairs(classified, flags):
            assert a < b, (a, b)

    def test_a_pair_needs_real_support_to_count_as_exclusive(self, everything):
        """Two flags that never co-occur because one is nearly unused prove
        nothing."""
        classified = _classified(everything)
        flags = [c for c in everything.columns if c.startswith('is_')]
        num = _numeric_flags(classified)
        course = classified['course_type'].astype(str).str.strip().str.lower()
        for name, a, b in learn_exclusive_pairs(classified, flags):
            pool = num[(course == name).values]
            assert (pool[a] == 1).sum() >= MIN_EXCLUSIVE_SUPPORT
            assert (pool[b] == 1).sum() >= MIN_EXCLUSIVE_SUPPORT


class TestConflictResolution:

    def test_the_name_beats_an_attribute(self):
        exclusive = {('bread', 'is_dosa', 'is_paratha')}
        # is_paratha proposed by an attribute (rank 0), is_dosa by the word
        kept = _resolve_conflicts({'is_paratha': 0, 'is_dosa': 3}, set(),
                                  'bread', exclusive)
        assert kept == ['is_dosa']

    def test_a_later_word_beats_an_earlier_one(self):
        """Indian dish names put the form last: `paneer_masala_dosa` is a dosa."""
        exclusive = {('bread', 'is_dosa', 'is_paratha')}
        kept = _resolve_conflicts({'is_paratha': 1, 'is_dosa': 3}, set(),
                                  'bread', exclusive)
        assert kept == ['is_dosa']

    def test_a_flag_the_row_already_carries_is_never_displaced(self):
        """That one is the ontology's own classification, not a proposal."""
        exclusive = {('bread', 'is_dosa', 'is_paratha')}
        kept = _resolve_conflicts({'is_dosa': 9}, {'is_paratha'}, 'bread',
                                  exclusive)
        assert kept == []

    def test_flags_that_are_not_exclusive_all_survive(self):
        kept = _resolve_conflicts({'is_dosa': 3, 'is_dosa_family': 3}, set(),
                                  'bread', set())
        assert sorted(kept) == ['is_dosa', 'is_dosa_family']


class TestPremiumIsTheClientsRuleNotTheDatas:
    """*"premium is a dish like paneer, baby corn, mushroom, a lot of vegetable
    will increase the cost of the items, and rich continental stuff"*."""

    @pytest.mark.parametrize('name', ['paneer_butter_masala', 'kadai_mushroom',
                                      'baby_corn_manchurian_gravy'])
    def test_the_ingredients_the_client_named_are_premium(self, name):
        assert is_premium({'item': name, 'key_ingredient': '',
                           'cuisine_family': 'north_indian'})

    def test_a_plain_vegetable_dish_is_not(self):
        assert not is_premium({'item': 'aloo_jeera_dry', 'key_ingredient': 'potato',
                               'cuisine_family': 'north_indian'})

    def test_plain_continental_is_not_rich_continental(self):
        """bruschetta, falafel and hummus are continental and are not premium —
        the client said *rich* continental."""
        for name in ('bruschetta', 'falafel', 'hummus_and_pita_bread'):
            assert not is_premium({'item': name, 'key_ingredient': '',
                                   'cuisine_family': 'continental'}), name
        assert is_premium({'item': 'vegetable_au_gratin', 'key_ingredient': '',
                           'cuisine_family': 'continental'})

    def test_baby_corn_is_reachable_from_the_name(self):
        """Regression, and the reason the predicate matches phrases not tokens:
        `baby_corn` is never a token of `baby_corn_manchurian_gravy`, so a token
        test silently missed every baby-corn dish — the very ingredient the
        client called out."""
        assert is_premium({'item': 'baby_corn_manchurian_gravy',
                           'key_ingredient': '', 'cuisine_family': 'north_indian'})
        assert is_premium({'item': 'cottage_cheese_tikka', 'key_ingredient': '',
                           'cuisine_family': 'north_indian'})

    def test_the_premium_rule_only_writes_to_its_own_courses(self, learned):
        """A `dal` is never given a premium flag by this channel, however
        paneer-ish its name — `PREMIUM_FLAG_BY_COURSE` is the whole scope."""
        learned_text, attribute_rules, flag_tokens, exclusive, _ = learned
        frame = _synthetic([
            {'item': 'paneer_makhani_dal', 'course_type': 'dal'},
            {'item': 'paneer_butter_masala', 'course_type': 'veg_gravy'},
        ])
        _, filled, _ = apply(frame, learned_text, attribute_rules, flag_tokens,
                             exclusive)
        premium = {(i, c) for i, c, _ in filled if c.startswith('is_premium')}
        assert not [i for i, _ in premium if i == 'paneer_makhani_dal']
        assert ('paneer_butter_masala', 'is_premium_veg') in premium

    def test_the_mixed_vegetable_catchall_was_not_applied(self, everything):
        """The one clause deliberately left out.

        Read as `key_ingredient == mixed_vegetables` it would mark hundreds more
        rows premium — rows the ontology explicitly flags as NOT premium — and
        `mixed_veg_curry` is the largest sub_category there is, so
        `premium_veg_gravy_exactly_one` would be choosing the day's premium dish
        out of nearly the whole pool.
        """
        num = _numeric_flags(everything)
        catchall = (everything['key_ingredient'].astype(str).str.strip()
                    .str.lower() == MIXED_VEG_CATCHALL)
        course = everything['course_type'].astype(str).str.strip().str.lower()
        scoped = catchall & course.isin(PREMIUM_FLAG_BY_COURSE)
        assert scoped.sum() > 100, 'the catch-all should still be widespread'
        # Some of them are premium for an unrelated reason (a paneer dish whose
        # key_ingredient is the catch-all), so this is a rate, not a zero.
        assert (num.loc[scoped, 'is_premium_veg'] == 1).mean() < 0.35


class TestFillsStayInsideTheirScope:
    """A blank `dal_region` on a dessert is not a gap — the column does not
    apply — and filling it would be inventing a fact about the row.

    Asserted against this script's own output rather than against the shipped
    workbooks, which carry 157 out-of-scope `flavoured_rice_region` values from
    the original mapping pipeline. Those predate this and are left alone; what
    matters is that nothing here adds to them.
    """

    @pytest.mark.parametrize('column', [c for c, s in COLUMN_SCOPE.items() if s])
    def test_a_scoped_column_is_never_filled_outside_its_courses(
            self, learned, column):
        learned_text, attribute_rules, flag_tokens, exclusive, _ = learned
        wrong_course = 'dessert' if 'dessert' not in COLUMN_SCOPE[column] \
            else 'veg_gravy'
        frame = _synthetic([
            {'item': 'gulab_jamun', 'course_type': wrong_course},
            {'item': 'moong_dal_tadka', 'course_type': wrong_course},
        ])
        out, filled, _ = apply(frame, learned_text, attribute_rules,
                               flag_tokens, exclusive)
        assert column not in {c for _, c, _ in filled}
        assert out[column].isna().all()


class TestTheTokenVoteIsDisciplined:

    def test_stopwords_never_justify_a_fill(self, everything):
        """`of` proposed `is_dairy_based` off `cream_of_spinach`, and `masala`
        proposed `is_deep_fried_starter` off `masala_puri`. Same failure, and
        same remedy, as `MODIFIER_STOPWORDS` in `fill_item_colours.py`."""
        classified = _classified(everything)
        flags = [c for c in everything.columns if c.startswith('is_')]
        learned = learn_flag_tokens(classified, flags)
        assert learned, 'no token implications learned at all'
        for (_, token) in learned:
            assert token not in TOKEN_STOPWORDS, token

    def test_it_only_proposes_values_the_ontology_already_uses(self, everything):
        classified = _classified(everything)
        flags = [c for c in everything.columns if c.startswith('is_')]
        known = set(flags)
        for proposed in learn_flag_tokens(classified, flags).values():
            assert proposed <= known


class TestRunningItAgainChangesNothing:

    def test_a_second_pass_fills_nothing(self, frames, learned):
        """Not merely tidiness: this script re-learns from its own output, so
        without converging inside one run every invocation would find more work
        and the workbooks would never settle."""
        learned_text, attribute_rules, flag_tokens, exclusive, _ = learned
        for city, d in frames.items():
            _, filled, _ = apply(d, learned_text, attribute_rules, flag_tokens,
                                 exclusive)
            assert not filled, (city, filled[:5])

    def test_the_flagless_rows_are_essentially_gone(self, frames):
        """The hole this existed to close: 1,598 Bangalore rows and 175 Chennai
        rows carried no flag at all."""
        assert int(flagless(frames['bangalore']).sum()) < 250
        assert int(flagless(frames['chennai']).sum()) < 25
        for city in ('pune', 'ncr'):
            assert int(flagless(frames[city]).sum()) < 5, city

    def test_a_fill_never_overwrites_what_was_already_there(self, frames, learned):
        """Monotone by construction: values only appear, never change."""
        learned_text, attribute_rules, flag_tokens, exclusive, _ = learned
        d = frames['chennai']
        out, _, _ = apply(d, learned_text, attribute_rules, flag_tokens, exclusive)
        for column in ('sub_category', 'key_ingredient', 'course_type', 'item'):
            had = d[column].notna()
            assert (out.loc[had, column].astype(str)
                    == d.loc[had, column].astype(str)).all(), column


class TestTheGapsThatAreLeftAreRealGaps:

    def test_what_it_could_not_settle_is_reported_not_guessed(self, frames):
        """`poriyal_kootu` and `sunda_vatha_kuzhambu` name a PREPARATION, and the
        ontology's rows for each are spread across whatever vegetable went in, so
        no token vote can converge. They were adjudicated by hand in
        `course_type_corrections.py` rather than filled by a guess."""
        d = frames['chennai'].set_index('item')
        assert _norm(d.at['sunda_vatha_kuzhambu', 'key_ingredient']) == 'turkey_berry'
        assert _norm(d.at['valakai_kara_curry', 'key_ingredient']) == 'raw_banana'
