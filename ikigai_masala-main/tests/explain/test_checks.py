"""The six plate verdicts, pinned.

No solver, no database, no network — hand-built dish dicts only, so a threshold
change shows up as a failing assertion rather than a menu that reads differently
and nobody notices.
"""

import pytest

from src.explain.checks import (
    MAIN_COURSES, Check, base_slot, check_colour_variety,
    check_no_ingredient_echo, check_non_dal_protein, check_richness_balance,
    check_spice_arc, check_texture_contrast, main_dishes, plate_profile,
    run_checks,
)


def dish(name, colour=None, texture=None, spice=None, rich=None,
         ing=None, protein=None, cuisine=None, course=None):
    return {'name': name, 'item_color': colour, 'texture': texture,
            'spice_level': spice, 'richness_score': rich,
            'key_ingredient': ing, 'primary_protein': protein,
            'cuisine_family': cuisine, 'course_type': course}


BALANCED = {
    'starter':        dish('punugulu', 'brown', 'crisp', 1, 3, 'rice_flour', 'rice'),
    'rice':           dish('raw_mango_rice', 'yellow', 'grainy', 1, 2, 'mango', 'rice'),
    'bread':          dish('jowar_roti', 'brown', 'bready', 0, 1, 'jowar', 'jowar'),
    'veg_dry__1':     dish('carrot_palya', 'orange', 'dry', 1, 2, 'carrot', 'green_peas'),
    'veg_dry__2':     dish('pumpkin_lobiya', 'yellow', 'dry', 1, 2, 'pumpkin', 'black_eyed_pea'),
    'veg_gravy':      dish('veg_kurma', 'green', 'saucy', 2, 4, 'mixed_veg', 'coconut'),
    'dal':            dish('tovve', 'yellow', 'saucy', 0, 2, 'toor_dal', 'toor_dal'),
    'nonveg_main__1': dish('egg_masala', 'orange', 'saucy', 2, 3, 'egg', 'egg'),
    # condiments must be ignored by every check
    'curd_side':      dish('curd', 'white', 'soft', 0, 1, 'curd', 'yogurt'),
    'welcome_drink':  dish('mint_juice', 'green', 'fresh', 0, 0, 'mint', None),
}


class TestScoping:
    def test_only_main_courses_count(self):
        m = main_dishes(BALANCED)
        assert 'curd_side' not in m and 'welcome_drink' not in m
        assert set(base_slot(s) for s in m) <= MAIN_COURSES

    def test_numbered_slots_map_to_their_base(self):
        assert base_slot('veg_dry__2') == 'veg_dry'
        assert base_slot('dal') == 'dal'

    def test_condiments_do_not_inflate_colour_count(self):
        """`white` comes only from curd; excluding condiments must drop it."""
        assert 'white' not in plate_profile(BALANCED)['colour_spread']


class TestColourVariety:
    def test_balanced_day_passes(self):
        assert check_colour_variety(BALANCED).passed

    def test_three_colours_fails(self):
        d = {k: dict(v, item_color='brown') for k, v in BALANCED.items()}
        d['rice'] = dict(d['rice'], item_color='yellow')
        d['dal'] = dict(d['dal'], item_color='green')
        assert not check_colour_variety(d).passed


class TestTextureContrast:
    def test_balanced_day_passes(self):
        assert check_texture_contrast(BALANCED).passed

    def test_all_saucy_plate_flags(self):
        """The check that has no equivalent in the existing ruleset.

        An all-gravy plate satisfies colour, spice, protein and cooldown. It is
        still mush, and `saucy` is 2,942 of 6,143 Bangalore rows, so the solver
        drifts here on its own.
        """
        d = {k: dict(v, texture='saucy') for k, v in BALANCED.items()}
        c = check_texture_contrast(d)
        assert not c.passed
        assert c.evidence['dominant'] == 'saucy'
        assert c.evidence['dominant_share'] == 1.0

    def test_missing_texture_data_does_not_invent_a_category(self):
        d = {k: dict(v, texture=None) for k, v in BALANCED.items()}
        c = check_texture_contrast(d)
        assert c.passed and c.evidence['total'] == 0

    @pytest.mark.parametrize('blank', ['', '  ', 'nan', 'NaN', 'None'])
    def test_blank_markers_are_not_a_texture(self, blank):
        d = {k: dict(v, texture=blank) for k, v in BALANCED.items()}
        assert check_texture_contrast(d).evidence['total'] == 0


class TestSpiceArc:
    def test_varied_spice_passes(self):
        assert check_spice_arc(BALANCED).passed

    def test_flat_spice_flags(self):
        d = {k: dict(v, spice_level=1) for k, v in BALANCED.items()}
        assert not check_spice_arc(d).passed

    def test_zero_is_a_real_level_not_a_missing_value(self):
        """spice_level 0 means mild. It must not be read as absent."""
        d = {k: dict(v, spice_level=0) for k, v in BALANCED.items()}
        d['veg_gravy'] = dict(d['veg_gravy'], spice_level=2)
        c = check_spice_arc(d)
        assert c.passed and c.evidence['spread'].get('mild', 0) > 0


class TestNonDalProtein:
    def test_peas_and_beans_count(self):
        assert check_non_dal_protein(BALANCED).passed

    def test_dal_only_flags(self):
        d = {k: dict(v, primary_protein='toor_dal') for k, v in BALANCED.items()}
        c = check_non_dal_protein(d)
        assert not c.passed
        assert 'only vegetarian protein' in c.detail


class TestIngredientEcho:
    def test_distinct_ingredients_pass(self):
        assert check_no_ingredient_echo(BALANCED).passed

    def test_paneer_twice_flags(self):
        """Legal under every current rule: different course, different colour."""
        d = dict(BALANCED)
        d['veg_gravy'] = dish('paneer_butter_masala', 'red', 'saucy', 1, 4, 'paneer', 'paneer')
        d['veg_dry__1'] = dish('paneer_tikka_dry', 'green', 'dry', 2, 3, 'paneer', 'paneer')
        c = check_no_ingredient_echo(d)
        assert not c.passed and c.evidence['repeats'] == {'paneer': 2}


class TestRichness:
    def test_mid_range_passes(self):
        assert check_richness_balance(BALANCED).passed

    @pytest.mark.parametrize('value,expected', [(5, False), (0, False), (2, True)])
    def test_extremes_flag(self, value, expected):
        d = {k: dict(v, richness_score=value) for k, v in BALANCED.items()}
        assert check_richness_balance(d).passed is expected


class TestRunner:
    def test_returns_all_six(self):
        out = run_checks(BALANCED)
        assert len(out) == 6
        assert all(isinstance(c, Check) for c in out)

    def test_a_broken_check_never_takes_the_request_down(self):
        """This layer describes a menu; it must never be why one fails."""
        assert run_checks({'rice': {'name': 'x'}}) != []

    def test_empty_day_is_survivable(self):
        assert run_checks({}) != []

    def test_every_check_is_json_serialisable(self):
        import json
        json.dumps([c.to_dict() for c in run_checks(BALANCED)])
