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


class TestTheFalsePositiveClasses:
    """The three defects the verified problem report found, pinned.

    Each was a check flagging something the menu was right to do. That is the
    expensive kind of wrong: a chef who opens this and sees it complain about
    the system's own correct output closes it and does not open it again.
    """

    def test_a_non_veg_plate_is_not_protein_thin(self):
        """`non_dal_protein` read only the vegetarian half of the column, so a
        day serving chicken and egg beside a toor dal came back "dal is the
        only vegetarian protein" — true as written, useless as a verdict. 59 of
        the fleet's 85 counters run a nonveg_main, so this was the majority
        configuration flagging for nothing."""
        from src.explain.checks import check_non_dal_protein
        d = {k: dict(v, primary_protein='toor_dal') for k, v in BALANCED.items()}
        d['nonveg_main__1'] = dish('chicken_masala', 'red', 'saucy', 2, 3,
                                   'chicken', 'chicken')
        c = check_non_dal_protein(d)
        assert c.passed
        assert c.evidence['skipped'] is True
        assert 'chicken' in c.evidence['nonveg_proteins']

    def test_a_pure_veg_plate_is_still_asked_the_question(self):
        """The check is still right where it was always the right question."""
        from src.explain.checks import check_non_dal_protein
        d = {k: dict(v, primary_protein='toor_dal') for k, v in BALANCED.items()}
        d.pop('nonveg_main__1')
        c = check_non_dal_protein(d)
        assert not c.passed and c.evidence['skipped'] is False

    def test_a_sentinel_ingredient_abstains_rather_than_flagging(self):
        """`mixed_vegetables` is 375 Bangalore rows and names no ingredient.
        Two dishes sharing it is a gap in the data, not an echo on the plate —
        and counting it as a pass would hide the gap just as badly."""
        from src.explain.checks import check_no_ingredient_echo
        d = dict(BALANCED)
        d['veg_gravy'] = dish('mix_veg_kurma', 'green', 'saucy', 1, 3,
                              'mixed_vegetables', 'coconut')
        d['veg_dry__1'] = dish('mix_veg_poriyal', 'orange', 'dry', 1, 2,
                               'mixed_vegetables', 'green_peas')
        c = check_no_ingredient_echo(d)
        assert c.passed
        assert 'mixed_vegetables' not in c.evidence['repeats']
        assert 'mixed_vegetables' in c.evidence['unknown']

    def test_a_real_echo_still_flags_beside_a_sentinel(self):
        """The abstain must not become a way to hide a genuine repeat."""
        from src.explain.checks import check_no_ingredient_echo
        d = dict(BALANCED)
        d['veg_gravy'] = dish('paneer_butter_masala', 'red', 'saucy', 1, 4,
                              'paneer', 'paneer')
        d['veg_dry__1'] = dish('paneer_tikka_dry', 'green', 'dry', 2, 3,
                               'paneer', 'paneer')
        d['dal'] = dish('mix_veg_dal', 'yellow', 'saucy', 0, 2,
                        'mixed_vegetables', 'toor_dal')
        d['starter'] = dish('mix_veg_cutlet', 'brown', 'crisp', 1, 3,
                            'mixed_vegetables', 'potato')
        c = check_no_ingredient_echo(d)
        assert not c.passed and c.evidence['repeats'] == {'paneer': 2}

    def test_colour_variety_uses_the_target_it_is_given(self):
        """A counter with three colour slots is legitimately asked for three.
        Judging it against a hardcoded 4 flags a day for obeying the rule that
        generated it — the one class of false alarm a chef cannot act on."""
        d = {'rice': BALANCED['rice'], 'dal': BALANCED['dal'],
             'veg_gravy': BALANCED['veg_gravy']}      # yellow, yellow, green
        assert not check_colour_variety(d).passed              # default 4
        assert check_colour_variety(d, target=2).passed

    def test_colour_variety_counts_the_slots_the_solver_counts(self):
        """`MAIN_COURSES` and `cfg.color_slots` are different sets — the solver
        counts `dessert` and not `bread`. Two questions under one name."""
        d = dict(BALANCED)
        d['dessert'] = dish('gulab_jamun', 'red', 'soft', 0, 5, 'milk', None)
        wide = check_colour_variety(d, slots={'rice', 'dal', 'dessert'})
        assert wide.evidence['counted_dishes'] == 3
        assert 'red' in wide.evidence['spread']        # dessert counted
        assert 'brown' not in wide.evidence['spread']  # bread not counted

    def test_the_target_is_clamped_to_the_dishes_actually_served(self):
        """The solver clamps to the colour cells the day has (design note 13).
        A two-dish day asked for four colours is unsatisfiable by arithmetic."""
        d = {'rice': BALANCED['rice'], 'dal': BALANCED['dal']}
        c = check_colour_variety(d, target=4)
        assert c.evidence['threshold'] == 2
        assert c.evidence['configured_target'] == 4


class TestTheCalibrationGate:
    def test_only_calibrated_verdicts_are_returned_when_gated(self):
        from src.explain.checks import CALIBRATED
        got = {c.name for c in run_checks(BALANCED, calibrated_only=True)}
        assert got == set(CALIBRATED)

    def test_the_gate_is_off_by_default(self):
        assert len(run_checks(BALANCED)) == 6

    def test_every_calibrated_name_is_a_real_check(self):
        """A typo here silently drops a verdict from the UI."""
        from src.explain.checks import CALIBRATED
        assert CALIBRATED <= {c.name for c in run_checks(BALANCED)}

    def test_the_two_checks_that_cannot_earn_a_line_are_excluded(self):
        """`spice_arc` and `richness_balance` fire on under 6% of days at these
        thresholds (49 observed, zero events, rule of three). Too loose to earn
        a line — see docs/explain_layer_calibration.md."""
        from src.explain.checks import CALIBRATED
        assert 'spice_arc' not in CALIBRATED
        assert 'richness_balance' not in CALIBRATED


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
