"""What an importer must refuse to mint, and what it must never refuse.

A correction to the item lists is only half a fix. `remove_generic_rows.py`'s
own note says the other half: the chain deletes a row at step 5 and the client
menu imports run at step 7, so the next import mints it again under whatever
spelling its own source uses. Three of the vegetarian-line corrections (note 34)
proved it — `kori_gassi`, `shami_kabab` and `hederabad_dum_biryani` all came
straight back, and the two salad-bar rows with them.

So the assertions here are in pairs: the thing is suppressed or folded, AND the
nearest legitimate thing to it is untouched. A guard that swallows real dishes
is worse than the rows it was added to stop.
"""

from __future__ import annotations

import pytest

from scripts.menu_import import (
    ALIASES, MAX_DISH_NAME_TOKENS, is_placeholder, to_item,
)

SALAD_BAR = (
    'Onion Rings, Carrots Batons, Chinese Cabbage, English Cucumber, '
    'Bell Pepper, Tomato Quarters, Boiled Chana, Boiled Peanuts, '
    'Boiled Rajma, Corn, Boiled Betroot, Boiled Eggs'
)


class TestADescriptionIsNotADishName:
    def test_the_salad_bar_is_refused(self):
        """23 tokens listing what is on a station. Imported straight it became a
        row filed `nonveg_main` — it ends in eggs — so the whole salad bar was a
        candidate for the day's meat dish."""
        assert is_placeholder(SALAD_BAR)

    def test_the_paneer_variant_is_refused_too(self):
        """MOengage's sheet carries two of these, and only one ends in eggs."""
        assert is_placeholder(SALAD_BAR.replace('Boiled Eggs', 'Paneer Cubes'))

    @pytest.mark.parametrize('name', [
        # The longest real names in the five city lists, at 10, 9 and 8 tokens.
        'Ghee Rice adequate ghee and authentic fried onion garnish grapes',
        'Mix veg salt and pepper roasted in combi oven',
        'Bhuna chicken masala in gujrati style chicken rasawala',
        'Cucumbers lime watermelon and mint flavor detox water',
        'Roasted peri herbed vegetable with milk cheese sauce',
        # and the ordinary case
        'Paneer Butter Masala',
    ])
    def test_a_real_dish_is_never_refused(self, name):
        assert not is_placeholder(name)

    def test_the_threshold_has_room_on_both_sides(self):
        """Measured, not guessed: the longest real name is 10 tokens and the
        shortest salad bar is 23. If either end ever closes on 14 this fails
        and the number needs re-deriving rather than nudging."""
        longest_real = len(
            'ghee_rice_adequate_ghee_and_authentic_fried_onion_garnish_grapes'
            .split('_'))
        shortest_bar = len(to_item(SALAD_BAR).split('_'))
        assert longest_real < MAX_DISH_NAME_TOKENS < shortest_bar
        assert MAX_DISH_NAME_TOKENS - longest_real >= 3
        assert shortest_bar - MAX_DISH_NAME_TOKENS >= 3

    def test_it_counts_tokens_and_not_characters(self):
        """A long name with few words is a dish; a short name with many words is
        a list. Counting characters would refuse the first and accept the
        second."""
        assert not is_placeholder('Thalassery Chicken Dum Biryani Special')
        assert is_placeholder('a b c d e f g h i j k l m n o p')


class TestTheVegetarianLineFoldsSurviveAnImport:
    @pytest.mark.parametrize('printed,expected', [
        # `kori` is Tulu for chicken, so this IS chicken_gassi. Without the
        # alias the next import mints a Mangalorean CHICKEN curry into a veg
        # pool again — Booking and Citrix both print it this way.
        ('Kori Gassi', 'chicken_gassi'),
        # A third spelling of shami kebab, the one Citrix's sheet uses.
        ('Shami Kabab', 'shami_kebab'),
        # `hederabad` is Hyderabad misspelled; the row it used to mint was
        # removed as a junk duplicate carrying no protein or sub_category.
        ('Hederabad Dum Biryani', 'hyderabad_veg_dum_biryani'),
    ])
    def test_the_printed_spelling_maps_onto_the_surviving_row(self, printed, expected):
        """Asserted through `to_item`, which is what the importers call, rather
        than against `ALIASES` directly — the dict being right is worth nothing
        if the fold is not actually applied on the path an import takes."""
        assert to_item(printed) == expected

    def test_the_alias_targets_are_real_rows(self, project_root_path):
        """An alias pointing at a name no city carries silently mints the target
        instead of folding onto it — the same failure with an extra step."""
        import pandas as pd
        from scripts.city_list import CITIES
        live = set()
        for city in CITIES:
            path = project_root_path / 'data' / 'raw' / 'city_items' / f'{city}.xlsx'
            df = pd.read_excel(path)
            df.columns = [c.strip() for c in df.columns]
            live |= {str(v).strip().lower() for v in df['item']}
        for source, target in ALIASES.items():
            assert target in live, f'{source} -> {target}, which no city has'

    def test_no_alias_points_at_something_that_is_also_aliased(self):
        """A chain would mean the fold depends on dict order."""
        for target in ALIASES.values():
            assert target not in ALIASES, target

    def test_the_chicken_fold_does_not_cross_the_veg_line_backwards(self):
        """`kori_gassi` -> `chicken_gassi` moves a name onto a NON-VEG row,
        which is the safe direction. The reverse — a meat name folded onto a
        vegetarian row — would put meat in a veg pool, so it is worth asserting
        that this alias is not that."""
        import pandas as pd
        from scripts.city_list import CITIES
        from src.constants import NONVEG_SLOTS
        for city in CITIES:
            path = (__import__('pathlib').Path(__file__).resolve().parents[2]
                    / 'data' / 'raw' / 'city_items' / f'{city}.xlsx')
            df = pd.read_excel(path)
            df.columns = [c.strip() for c in df.columns]
            hit = df[df['item'].astype(str).str.strip().str.lower() == 'chicken_gassi']
            if len(hit):
                assert str(hit.iloc[0]['course_type']).strip().lower() in NONVEG_SLOTS
