"""One dish written twice, found by meaning rather than by spelling.

A report, so the tests are about the PREDICATE being trustworthy — a grouping
rule that over-merges would propose deleting real dishes, and one that
under-merges is the hand-written list it exists to replace.
"""

from __future__ import annotations

import pytest

from scripts.audit_duplicate_dish_names import (
    FORM_WORDS, PHRASES, SYNONYMS, collect, dish_key, propose, write_report,
)


class TestTheGroupingKey:
    @pytest.mark.parametrize('a,b', [
        # word order
        ('aloo_dum', 'dum_aloo'),
        ('achari_bhindi', 'bhindi_achari'),
        # a synonym in another language
        ('bhuna_chicken_masala', 'bhuna_murgh_masala'),
        ('chicken_gassi', 'kori_gassi'),
        # both at once — the client's own example
        ('chicken_pepper', 'murgh_kalimirchi'),
        ('chicken_kali_mirch', 'murg_pepper'),
        # spelling families the word-level fold does not carry
        ('murgh_razala', 'murgh_rezalla'),
    ])
    def test_two_names_for_one_dish_collapse(self, a, b):
        assert dish_key(a) == dish_key(b), (dish_key(a), dish_key(b))

    @pytest.mark.parametrize('a,b', [
        # FORM is what separates two real dishes, and it is the distinction the
        # whole audit turns on. A dry and a gravy of the same ingredients are
        # not one row written twice.
        ('pepper_chicken_dry', 'pepper_chicken_gravy'),
        ('chicken_tikka', 'chicken_curry'),
        ('veg_biryani', 'veg_pulao'),
        # different ingredients
        ('aloo_mutter', 'gobi_mutter'),
        # `kodi guddu` is the EGG, `kodi kura` the chicken — the phrase pass is
        # what keeps them apart, and folding `kodi` alone would merge them.
        ('kodi_guddu_masala', 'kodi_kura'),
    ])
    def test_two_real_dishes_stay_apart(self, a, b):
        assert dish_key(a) != dish_key(b)

    def test_a_phrase_beats_its_own_tokens(self):
        """`kodi_guddu` must be read whole. Token-by-token it is chicken + egg,
        and the dish is an egg dish."""
        assert dish_key('kodi_guddu')[0] == 'egg'

    def test_no_synonym_changes_what_the_dish_is(self):
        """Every entry maps a word to another word for the SAME thing. A pair
        that crossed the veg line (say `paneer` -> `chicken`) would merge a
        vegetarian dish into a meat one."""
        meat = {'chicken', 'egg', 'mutton', 'fish', 'prawn'}
        veg = {'paneer', 'soya', 'soy', 'gobi', 'aloo', 'mushroom', 'veg',
               'chana', 'matar', 'mutter'}
        for word, canon in SYNONYMS.items():
            assert not (word in veg and canon in meat), f'{word} -> {canon}'
            assert not (word in meat and canon in veg), f'{word} -> {canon}'
        for phrase, canon in PHRASES.items():
            assert not (canon in meat and any(v in phrase for v in veg)), phrase

    def test_a_form_word_is_never_also_a_synonym(self):
        """A word cannot both name the form and be folded away, or the two
        halves of the key disagree about where it went."""
        assert not (set(SYNONYMS) & FORM_WORDS)
        assert not (set(SYNONYMS.values()) & FORM_WORDS)


class TestTheProposedName:
    def test_the_english_protein_word_wins(self):
        """`chicken` is what every other row and every menu reader uses."""
        assert propose(['murgh_kalimirchi', 'chicken_pepper']) == 'chicken_pepper'
        assert propose(['kori_gassi', 'chicken_gassi']) == 'chicken_gassi'

    def test_it_is_deterministic(self):
        names = ['aloo_dum', 'dum_aloo']
        assert propose(names) == propose(list(reversed(names)))

    def test_it_proposes_one_of_the_real_names(self):
        """Never a synthesised name — the survivor has to be a row that exists."""
        names = ['bhuna_murgh_masala', 'chicken_bhuna_masala']
        assert propose(names) in names


@pytest.fixture(scope='module')
def report():
    return collect()


class TestWhatItFinds:
    def test_it_finds_the_duplicates_that_are_known_to_be_there(self, report):
        dupes, _ = report
        names = {n for d in dupes for n in d['names'].split(' | ')}
        for known in ('dum_aloo', 'bhuna_murgh_masala', 'murgh_razeela'):
            assert known in names, known

    def test_a_group_never_mixes_two_courses(self, report):
        """That is the misfile bucket's job. A duplicate group whose rows
        disagree about `course_type` would propose merging away the evidence
        that one of them is filed wrongly."""
        dupes, _ = report
        for d in dupes:
            assert ' | ' not in d['courses'], d

    def test_the_misfiles_carry_a_reason(self, report):
        _dupes, misfiles = report
        for m in misfiles:
            assert m['why_not_a_merge'] in (
                'course_type disagrees', 'primary_protein disagrees')
            assert ' | ' in m['courses'] or ' | ' in m['proteins']

    def test_a_blank_protein_is_not_a_disagreement(self, report):
        """`str(NaN)` is `'nan'`, which is truthy — reading it as a value made
        every blank-vs-filled pair look like a protein conflict, and 20 real
        duplicates were reported as misfiles."""
        _dupes, misfiles = report
        for m in misfiles:
            if m['why_not_a_merge'] == 'primary_protein disagrees':
                vals = [v for v in m['proteins'].split(' | ') if v]
                assert len(vals) > 1 and '(blank)' not in vals, m

    def test_every_group_has_at_least_two_names(self, report):
        dupes, misfiles = report
        for entry in dupes + misfiles:
            assert len(entry['names'].split(' | ')) >= 2

    def test_it_is_finding_a_real_amount(self, report):
        """A key that matched nothing would pass every test above."""
        dupes, misfiles = report
        assert len(dupes) > 200
        assert len(misfiles) > 5

    def test_the_committed_csv_is_current(self, report, project_root_path):
        """A stale report proposes merging rows that have since been folded."""
        dupes, misfiles = report
        expected = write_report(dupes, misfiles)
        path = project_root_path / 'docs' / 'duplicate_dish_names.csv'
        assert path.exists()
        assert path.read_text(encoding='utf-8') == expected, (
            'run `python scripts/audit_duplicate_dish_names.py`')


class TestItDoesNotContradictTheCorrectionsAlreadyApplied:
    def test_the_rows_already_folded_are_not_proposed_again(self, report):
        """`vegnonveg_corrections.py` folded six pairs. A report still naming
        them would ask the client to decide something already decided."""
        dupes, misfiles = report
        names = {n for e in dupes + misfiles for n in e['names'].split(' | ')}
        for gone in ('kori_gassi', 'kolkata_chic_curry', 'kasturia_kebab',
                     'chilli_chiken', 'tandoori_chcien',
                     'honey_chilli_chiciken'):
            assert gone not in names, f'{gone} was folded away already'
