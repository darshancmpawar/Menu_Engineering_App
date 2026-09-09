"""One dish written twice, found by meaning rather than by spelling.

A report, so the tests are about the PREDICATE being trustworthy — a grouping
rule that over-merges would propose deleting real dishes, and one that
under-merges is the hand-written list it exists to replace.
"""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.audit_duplicate_dish_names import (
    FORM_WORDS, PHRASES, SYNONYMS, _ITEMS, collect, dish_key, propose,
    write_report,
)
from scripts.city_list import CITIES


class TestTheGroupingKey:
    def test_a_phrase_that_prefixes_another_is_rewritten_first(self):
        """PHRASES are substring replacements and one is a PREFIX of another:
        `kali_mirch -> pepper` fired inside `kali_mirchi` and left `pepperi`,
        so every `*_kali_mirchi` row silently failed to group with its
        `kali_mirch` twin. A missed fold rather than a wrong one, which is why
        it went unnoticed — and the importer then minted the variant back as a
        new row."""
        assert dish_key('paneer_kali_mirchi') == dish_key('paneer_kali_mirch')
        assert dish_key('paneer_kali_mirchi') == dish_key('paneer_pepper')
        assert 'pepperi' not in dish_key('paneer_kali_mirchi')[0]

    def test_a_connector_word_is_not_part_of_the_dish(self):
        """`and` joins two ingredients and says nothing about the dish. The
        ontology writes both forms, and the importer's similarity path caught
        the pair only while the word order happened to line up — once the fold
        reordered the surviving name, similarity fell below its cutoff and
        `carrot_and_beans_poriyal` was minted back beside
        `beans_carrot_poriyal`."""
        assert dish_key('carrot_and_beans_poriyal') == dish_key('beans_carrot_poriyal')
        assert dish_key('potato_and_leek_soup') == dish_key('potato_leek_soup')
        assert 'and' not in dish_key('cucumber_and_lemon_water')[0].split('|')

    @pytest.mark.parametrize('a,b', [
        # word order
        ('aloo_dum', 'dum_aloo'),
        ('achari_bhindi', 'bhindi_achari'),
        # peas, transliterated two ways in one city — the split left NCR
        # holding four rows of methi malai peas
        ('methi_malai_mutter', 'matar_methi_malai'),
        # garlic, four ways, all in the dal slot
        ('dal_lasooni', 'dal_lehsooni'),
        ('lehsuni_dal_tadka', 'lasooni_dal_tadka'),
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
    def test_the_names_it_was_written_for_are_no_longer_in_any_city(self, report):
        """This used to assert the report FOUND `dum_aloo` and
        `murgh_razeela`. `fold_duplicate_dish_names.py` has since merged all
        330 groups, so the premise inverted: the report is empty and these
        names are gone. The predicate that grouped them is pinned above, on
        synthetic names, where folding the data cannot make it pass vacuously.
        """
        dupes, misfiles = report
        assert dupes == [] and misfiles == []
        # Scoped to the cities that HELD the pair, because the fold is
        # per-city and a name is only a duplicate where its twin lives. NCR
        # keeps `dum_aloo` and is right to: it has no `aloo_dum`.
        for city in ('bangalore', 'hyderabad'):
            names = set(pd.read_excel(_ITEMS / f'{city}.xlsx')['item']
                        .astype(str).str.lower().str.strip())
            for folded in ('dum_aloo', 'bhuna_murgh_masala', 'murgh_razeela',
                           'mutter_paneer', 'kadhai_paneer'):
                assert folded not in names, (city, folded)
            for kept in ('aloo_dum', 'bhuna_chicken_masala', 'chicken_razala',
                         'matar_paneer', 'kadai_paneer'):
                assert kept in names, (city, kept)

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

    def test_an_empty_report_means_folded_and_not_broken(self, report):
        """The vacuity guard, restated for a world where 0 is the right answer.

        It used to be `len(dupes) > 200` — a key that matched nothing would
        otherwise pass every test in this file. Now that the fold has run, a
        `dish_key` broken to return a constant, or one broken to return
        something unique per row, BOTH report zero groups and look like
        success. So the guard is that the predicate still does its job on rows
        the workbooks really hold: two names that must group, two that must
        not, and a real corpus underneath.
        """
        dupes, misfiles = report
        assert dupes == [] and misfiles == []

        rows = 0
        for city in CITIES:
            path = _ITEMS / f'{city}.xlsx'
            if path.exists():
                rows += len(pd.read_excel(path))
        assert rows > 5000, 'collect() is reading almost nothing'

        # not a constant key...
        assert dish_key('aloo_dum') != dish_key('paneer_butter_masala')
        # ...and not a unique-per-name one.
        assert dish_key('aloo_dum') == dish_key('dum_aloo')

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
