"""Which dishes complement each other — `src/explain/pairings.py`.

Hand-built plates only. No solver, no ontology, no network: a pairing is a
claim about two recorded attribute values, so it can be pinned exactly, and a
threshold change has to fail an assertion instead of quietly changing how a
menu reads.

Two properties matter more than any individual rule and are asserted directly:

  * **it must not flatter a plate.** A hot dish with no yogurt, or rich dishes
    with nothing light, produces a GAP. This is the half that makes the feature
    a diagnostic rather than marketing copy, and it is the half a caller could
    most easily filter out by accident.
  * **every line must introduce a dish.** Without that the rules pile onto
    whichever dish scores extremely and contradict each other — a real plate
    had `veg_fried_rice` called the day's rich dish and then its crisp relief.
"""

from __future__ import annotations

from src.explain.pairings import (
    HOT_SPICE, LIGHT_AT, RICH_AT, SOFT_SHARE_FOR_RELIEF, build_pairings,
    pair_carrier, pair_cooling, pair_crunch, pair_dry_against_saucy,
    pair_lightener,
)


def dish(name, **cols):
    """A plate entry in the shape `evidence.build_dishes` produces."""
    return {'name': name, **cols}


def plate(**slots):
    return {slot: dish(**attrs) if isinstance(attrs, dict) else dish(attrs)
            for slot, attrs in slots.items()}


HOT_CURRY = {'name': 'chicken_chettinad', 'spice_level': 3, 'texture': 'saucy',
             'richness_score': 4, 'course_type': 'nonveg_main'}
RAITA = {'name': 'boondi_raita', 'primary_protein': 'yogurt',
         'texture': 'fresh', 'richness_score': 1}
CHAPATI = {'name': 'wheat_chapati', 'texture': 'bready', 'richness_score': 2}
DRY_VEG = {'name': 'bhindi_masala', 'texture': 'dry', 'richness_score': 2}


class TestCooling:
    def test_a_hot_dish_and_the_yogurt_that_answers_it(self):
        p = pair_cooling({'nonveg_main': HOT_CURRY, 'curd_side': RAITA})
        assert p is not None
        assert p.kind == 'cooling'
        assert p.dishes == ['chicken_chettinad', 'boondi_raita']
        assert p.evidence['spice_level'] == 3
        assert 'boondi raita' in p.detail and 'cools it' in p.detail

    def test_a_curd_with_no_recorded_protein_still_counts(self):
        """A plain curd's row leaves `primary_protein` blank often enough that
        reading only the protein would miss the commonest cooling dish. The
        SLOT is the other half of the definition."""
        p = pair_cooling({'nonveg_main': HOT_CURRY,
                          'curd': {'name': 'plain_curd'}})
        assert p is not None
        assert p.evidence['cooling_slot'] == 'curd'

    def test_a_mild_plate_gets_no_cooling_claim(self):
        mild = {'name': 'aloo_jeera', 'spice_level': 1, 'texture': 'dry'}
        assert pair_cooling({'veg_dry': mild, 'curd_side': RAITA}) is None

    def test_the_threshold_is_the_stated_one(self):
        """`HOT_SPICE` is where a cooling side stops being optional. Pinned so
        moving it is a deliberate act with a failing test."""
        assert HOT_SPICE == 2
        at = {'name': 'x', 'spice_level': HOT_SPICE, 'course_type': 'veg_gravy'}
        below = {'name': 'x', 'spice_level': HOT_SPICE - 1,
                 'course_type': 'veg_gravy'}
        assert pair_cooling({'veg_gravy': at, 'curd_side': RAITA}) is not None
        assert pair_cooling({'veg_gravy': below, 'curd_side': RAITA}) is None

    def test_a_blank_spice_level_is_not_read_as_hot(self):
        for blank in (None, '', 'nan', 'NaN'):
            assert pair_cooling({'veg_gravy': {'name': 'x',
                                               'spice_level': blank},
                                 'curd_side': RAITA}) is None, blank


class TestLightener:
    def test_a_rich_dish_against_a_light_one(self):
        p = pair_lightener({'nonveg_main': HOT_CURRY, 'salad': RAITA})
        assert p is not None
        assert p.evidence == {'rich_score': 4, 'light_score': 1, 'scale_max': 5}

    def test_one_dish_is_never_both_sides(self):
        """A single dish scoring 4 cannot also be the plate's lightener, and
        `LIGHT_AT <= RICH_AT` means a mid-scale dish could satisfy both."""
        only = {'name': 'solo', 'richness_score': RICH_AT}
        assert pair_lightener({'veg_gravy': only}) is None

    def test_an_unscored_dish_is_not_nominated_as_light(self):
        """A blank `richness_score` read as 0 would make an undescribed dish
        the argument for why the plate works."""
        assert pair_lightener({'nonveg_main': HOT_CURRY,
                               'salad': {'name': 'unscored'}}) is None


class TestCrunch:
    SOFT_PLATE = {
        'veg_gravy': {'name': 'a', 'texture': 'saucy'},
        'dal': {'name': 'b', 'texture': 'saucy'},
        'rice': {'name': 'c', 'texture': 'soft'},
        'starter': {'name': 'papad', 'texture': 'crisp'},
    }

    def test_bite_on_a_soft_plate(self):
        p = pair_crunch(self.SOFT_PLATE)
        assert p is not None
        assert p.dishes == ['papad']
        assert p.evidence['soft_share'] >= SOFT_SHARE_FOR_RELIEF

    def test_a_varied_plate_gets_no_relief_claim(self):
        """Calling a crisp dish "relief" on a plate that is already varied is
        the overclaim that makes the rest of the output suspect."""
        varied = {'veg_gravy': {'name': 'a', 'texture': 'saucy'},
                  'veg_dry': DRY_VEG,
                  'bread': CHAPATI,
                  'starter': {'name': 'papad', 'texture': 'crisp'}}
        assert pair_crunch(varied) is None

    def test_a_plate_with_no_recorded_textures_abstains(self):
        assert pair_crunch({'veg_gravy': {'name': 'a'},
                            'dal': {'name': 'b'}}) is None


class TestCarrierAndContrast:
    def test_a_gravy_and_the_bread_that_carries_it(self):
        p = pair_carrier({'veg_gravy': {'name': 'dal_tadka',
                                        'texture': 'saucy'},
                          'bread': CHAPATI})
        assert p is not None
        assert p.dishes == ['dal_tadka', 'wheat_chapati']

    def test_rice_carries_too(self):
        """By texture rather than by slot: a counter serves rice from `rice`,
        `white_rice`, `healthy_rice` or a biryani in `nonveg_main`."""
        p = pair_carrier({'veg_gravy': {'name': 'g', 'texture': 'saucy'},
                          'white_rice': {'name': 'steamed_rice',
                                         'texture': 'grainy'}})
        assert p is not None and 'steamed rice' in p.detail

    def test_a_dry_dish_against_a_saucy_one(self):
        p = pair_dry_against_saucy({'veg_dry': DRY_VEG,
                                    'veg_gravy': {'name': 'g',
                                                  'texture': 'saucy'}})
        assert p is not None and p.kind == 'contrast'

    def test_an_all_saucy_plate_has_no_contrast_to_report(self):
        assert pair_dry_against_saucy(
            {'veg_gravy': {'name': 'a', 'texture': 'saucy'},
             'dal': {'name': 'b', 'texture': 'saucy'}}) is None

    def test_a_condiment_can_carry_but_cannot_be_a_main(self):
        """The whole plate supplies the PARTNER (a papad, a curd, a white rice),
        while the dish being explained comes from `MAIN_COURSES`. Otherwise a
        day's argument could rest entirely on its condiments."""
        assert pair_dry_against_saucy(
            {'curd_side': {'name': 'c', 'texture': 'dry'},
             'papad': {'name': 'p', 'texture': 'saucy'}}) is None


class TestTheGapsAreNeverHidden:
    def test_a_hot_plate_with_no_yogurt_says_so(self):
        out = build_pairings({'nonveg_main': HOT_CURRY, 'bread': CHAPATI})
        assert out['gaps'], out
        assert any('no curd or raita' in g for g in out['gaps'])
        assert 'chicken chettinad' in out['gaps'][0]

    def test_a_rich_plate_with_nothing_light_says_so(self):
        out = build_pairings({
            'nonveg_main': {'name': 'butter_chicken', 'richness_score': 5,
                            'texture': 'saucy', 'course_type': 'nonveg_main'},
            'veg_gravy': {'name': 'shahi_paneer', 'richness_score': 4,
                          'texture': 'saucy'}})
        assert any('nothing on the plate is light' in g for g in out['gaps'])

    def test_a_plate_with_no_complement_is_not_called_balanced(self):
        out = build_pairings({'nonveg_main': HOT_CURRY})
        assert not out['pairings']
        assert out['summary'].startswith('nothing on this plate offsets it')

    def test_a_gap_is_reported_alongside_the_pairings_that_did_hold(self):
        """The summary must not let good news bury the gap — a plate can be
        well put together in three ways and still be missing the yogurt."""
        out = build_pairings({
            'nonveg_main': HOT_CURRY, 'veg_dry': DRY_VEG, 'bread': CHAPATI,
            'salad': {'name': 'green_salad', 'richness_score': 1,
                      'texture': 'fresh'}})
        assert out['pairings'] and out['gaps']
        assert 'gap' in out['summary']

    def test_a_bare_plate_admits_it_has_nothing_to_go_on(self):
        out = build_pairings({'veg_gravy': {'name': 'mystery'}})
        assert not out['pairings'] and not out['gaps']
        assert 'not enough recorded' in out['summary']

    def test_no_gap_is_invented_for_a_plate_that_earns_none(self):
        out = build_pairings({'nonveg_main': HOT_CURRY, 'curd_side': RAITA,
                              'veg_dry': DRY_VEG, 'bread': CHAPATI})
        assert out['gaps'] == []


class TestEveryLineEarnsItsPlace:
    def test_a_claim_naming_only_already_discussed_dishes_is_dropped(self):
        """The defect this was written for: one real Tuesday plate had
        `veg_fried_rice` nominated as the day's RICH dish and then, two lines
        later, as its crisp RELIEF. Both true of the columns and contradictory
        as advice."""
        both = {'name': 'veg_fried_rice', 'richness_score': RICH_AT,
                'texture': 'crisp', 'course_type': 'rice'}
        out = build_pairings({
            'rice': both,
            'veg_gravy': {'name': 'g', 'texture': 'saucy',
                          'richness_score': 3},
            'dal': {'name': 'd', 'texture': 'saucy', 'richness_score': 3},
            'salad': {'name': 'salad', 'richness_score': LIGHT_AT,
                      'texture': 'fresh'}})
        kinds = [p['kind'] for p in out['pairings']]
        assert 'lightener' in kinds
        assert 'crunch' not in kinds, out['pairings']

    def test_a_partner_is_chosen_from_dishes_not_yet_mentioned(self):
        """`cooling` and `lightener` both like the raita, and using it twice
        spends two lines saying one thing."""
        out = build_pairings({
            'nonveg_main': HOT_CURRY,
            'curd_side': RAITA,
            'salad': {'name': 'kachumber', 'richness_score': LIGHT_AT,
                      'texture': 'fresh'}})
        lightener = [p for p in out['pairings'] if p['kind'] == 'lightener']
        assert lightener, out['pairings']
        assert 'kachumber' in lightener[0]['dishes']
        assert 'boondi_raita' not in lightener[0]['dishes']

    def test_no_dish_name_is_invented(self):
        """Everything named must be ON the plate — that is what keeps the
        prose validator able to accept a paraphrase of these lines."""
        dishes = {'nonveg_main': HOT_CURRY, 'curd_side': RAITA,
                  'veg_dry': DRY_VEG, 'bread': CHAPATI,
                  'salad': {'name': 's', 'richness_score': 1,
                            'texture': 'fresh'}}
        on_plate = {d['name'] for d in dishes.values()}
        out = build_pairings(dishes)
        for p in out['pairings']:
            assert set(p['dishes']) <= on_plate, p
            assert set(p['slots']) <= set(dishes), p

    def test_the_result_is_stable_across_runs(self):
        """`dishes` is keyed by slot id and its order follows the solution,
        which is not a contract this module may rely on."""
        dishes = {'veg_gravy': {'name': 'a', 'texture': 'saucy'},
                  'dal': {'name': 'b', 'texture': 'saucy'},
                  'bread': CHAPATI, 'veg_dry': DRY_VEG}
        first = build_pairings(dishes)
        shuffled = dict(reversed(list(dishes.items())))
        assert build_pairings(shuffled) == first

    def test_a_rule_that_raises_does_not_take_the_day_down(self):
        """Same rule as `run_checks`: this describes a menu and must never be
        why one fails to render."""
        class Exploding(dict):
            def get(self, *a, **k):
                raise RuntimeError('boom')

        out = build_pairings({'veg_gravy': Exploding(name='x')})
        assert out['pairings'] == []
        assert out['summary']


# ---------------------------------------------------------------------------
# The rules added for "more pairs": protein backbone, mild relief, and the
# dessert against the meal it follows. Each was added because the plate was
# carrying a fact the overview never mentioned; each is also a new chance to
# overclaim, which is what these pin.
# ---------------------------------------------------------------------------

from src.explain.pairings import (  # noqa: E402
    HEAVY_MEAL_MEAN, LIGHT_MEAL_MEAN, pair_mild_relief, pair_protein_backbone,
    pair_sweet_finish,
)


class TestProteinBackbone:
    def test_two_sources_are_both_named(self):
        p = pair_protein_backbone(plate(
            veg_gravy={'name': 'paneer_butter_masala', 'primary_protein': 'paneer'},
            veg_dry={'name': 'soya_keema', 'primary_protein': 'soy'},
        ))
        assert p is not None and p.kind == 'protein'
        assert p.evidence['distinct_proteins'] == 2
        assert 'paneer butter masala' in p.detail
        assert 'soya keema' in p.detail

    def test_the_count_never_exceeds_the_dishes_it_names(self):
        """A sentence naming two dishes and claiming three sources reads as if
        the two WERE the three, and a reader counting them finds the number
        wrong. Up to three are named; beyond that the remainder is stated as a
        remainder rather than folded into the same clause."""
        p = pair_protein_backbone(plate(
            veg_gravy={'name': 'a_gravy', 'primary_protein': 'paneer'},
            veg_dry={'name': 'b_dry', 'primary_protein': 'soy'},
            dal={'name': 'c_dal', 'primary_protein': 'toor_dal'},
            rice={'name': 'd_rice', 'primary_protein': 'green_peas'},
        ))
        assert p is not None
        named = sum(1 for n in ('a gravy', 'b dry', 'c dal', 'd rice')
                    if n in p.detail)
        assert named == len(p.dishes) == 3
        assert 'more protein source' in p.detail

    def test_one_source_is_stated_as_a_fact_not_a_compliment(self):
        p = pair_protein_backbone(plate(
            veg_dry={'name': 'soya_palya', 'primary_protein': 'soy'},
            bread={'name': 'plain_chapati'},
        ))
        assert p is not None
        assert p.evidence['distinct_proteins'] == 1
        assert 'only protein' in p.detail

    def test_yogurt_is_not_the_days_protein(self):
        """A raita is the cooling side and `pair_cooling` speaks for it.
        Counting it here would let a plate with no protein at all claim one."""
        assert pair_protein_backbone(plate(
            curd_side=RAITA, bread=CHAPATI)) is None

    def test_a_blank_protein_is_not_a_protein(self):
        assert pair_protein_backbone(plate(
            veg_dry={'name': 'aloo_jeera', 'primary_protein': None},
            veg_gravy={'name': 'mixed_veg', 'primary_protein': 'nan'},
        )) is None


class TestMildRelief:
    HOT = {'name': 'gobi_65', 'spice_level': 3, 'course_type': 'starter'}
    MILD = {'name': 'aloo_jeera', 'spice_level': 0, 'course_type': 'veg_dry'}

    def test_a_hot_dish_and_the_mild_one_to_fall_back_on(self):
        p = pair_mild_relief(plate(starter=self.HOT, veg_dry=self.MILD))
        assert p is not None and p.kind == 'relief'
        assert p.dishes == ['gobi_65', 'aloo_jeera']
        assert 'no curd' in p.detail

    def test_it_stands_down_when_there_is_a_cooling_dish(self):
        """`pair_cooling` is the better answer and runs first. Without this
        gate a plate with a raita gets two sentences about one dish's heat —
        the shared-slot guard cannot catch it, because the second line does
        introduce a new dish."""
        assert pair_mild_relief(plate(
            starter=self.HOT, veg_dry=self.MILD, curd_side=RAITA)) is None

    def test_it_needs_an_actual_gap_in_heat(self):
        assert pair_mild_relief(plate(
            starter=self.HOT,
            veg_dry={'name': 'chilli_paneer', 'spice_level': 3},
        )) is None

    def test_nothing_hot_means_nothing_to_relieve(self):
        assert pair_mild_relief(plate(veg_dry=self.MILD, bread=CHAPATI)) is None


class TestSweetFinish:
    """Desserts are richness 4 or 5 on 365 of 367 Bangalore rows.

    So the dessert's own score carries almost no information and the rule has
    to speak about the MAINS or stay silent. A line printed every single day is
    a line nobody reads, and it crowds out one that would have been read.
    """
    SWEET = {'name': 'gulab_jamun', 'richness_score': 5, 'course_type': 'dessert'}

    def test_silent_on_an_ordinary_plate(self):
        mid = (HEAVY_MEAL_MEAN + LIGHT_MEAL_MEAN) / 2
        assert pair_sweet_finish(plate(
            dessert=self.SWEET,
            veg_gravy={'name': 'aloo_matar', 'richness_score': mid},
        )) is None

    def test_speaks_when_the_meal_is_already_heavy(self):
        p = pair_sweet_finish(plate(
            dessert=self.SWEET,
            veg_gravy={'name': 'paneer_butter_masala', 'richness_score': 5},
            nonveg_main={'name': 'butter_chicken', 'richness_score': 5},
        ))
        assert p is not None and 'heavy lunch' in p.detail

    def test_speaks_when_it_is_the_only_rich_thing(self):
        p = pair_sweet_finish(plate(
            dessert=self.SWEET,
            veg_dry={'name': 'beans_poriyal', 'richness_score': 1},
            dal={'name': 'thin_rasam', 'richness_score': 1},
        ))
        assert p is not None and 'one rich thing' in p.detail

    def test_no_dessert_no_claim(self):
        assert pair_sweet_finish(plate(veg_dry=DRY_VEG, bread=CHAPATI)) is None


class TestTheLightenerPrefersARealDish:
    """`richness_score` alone cannot pick the light side.

    Welcome drinks are 1 on 191 of 198 Bangalore rows, salads on 321 of 326 and
    curd sides on 35 of 37. Asked for "the least rich dish" over the flat plate,
    the pool returns whichever of a hundred 1s sorts first — which is how a real
    Wednesday answered a rich dum chicken biryani with `pomegranate mint water`.
    True, and useless as advice.
    """
    RICH = {'name': 'dum_biryani', 'richness_score': 5,
            'course_type': 'nonveg_main'}
    LIGHT_MAIN = {'name': 'beans_poriyal', 'richness_score': 1,
                  'course_type': 'veg_dry'}
    SALAD = {'name': 'kachumber', 'richness_score': 1, 'course_type': 'salad'}
    DRINK = {'name': 'mint_water', 'richness_score': 1,
             'course_type': 'welcome_drink'}

    def test_a_main_beats_a_salad_and_a_drink(self):
        p = pair_lightener({'nonveg_main': self.RICH, 'veg_dry': self.LIGHT_MAIN,
                            'salad': self.SALAD, 'welcome_drink': self.DRINK})
        assert p is not None and p.dishes[1] == 'beans_poriyal'

    def test_a_salad_beats_a_drink(self):
        p = pair_lightener({'nonveg_main': self.RICH, 'salad': self.SALAD,
                            'welcome_drink': self.DRINK})
        assert p is not None and p.dishes[1] == 'kachumber'

    def test_a_drink_is_still_better_than_saying_nothing(self):
        """The tiers narrow the choice; they must not remove the answer."""
        p = pair_lightener({'nonveg_main': self.RICH, 'welcome_drink': self.DRINK})
        assert p is not None and p.dishes[1] == 'mint_water'


class TestTheNewRulesKeepTheOldProperties:
    def test_no_line_repeats_a_plate_that_has_only_one_idea(self):
        """The whole-plate guard still holds with eight rules instead of five:
        every rendered pairing must introduce a dish nobody has read about."""
        out = build_pairings({
            'nonveg_main': HOT_CURRY, 'curd_side': RAITA, 'bread': CHAPATI,
            'veg_dry': DRY_VEG,
            'dessert': {'name': 'kheer', 'richness_score': 5,
                        'course_type': 'dessert'},
        })
        seen: set = set()
        for p in out['pairings']:
            assert set(p['slots']) - seen, f'{p["detail"]!r} names nothing new'
            seen |= set(p['slots'])

    def test_no_dish_name_is_invented(self):
        out = build_pairings({
            'nonveg_main': HOT_CURRY, 'curd_side': RAITA, 'bread': CHAPATI,
            'veg_dry': {'name': 'soya_keema', 'primary_protein': 'soy',
                        'texture': 'dry'},
        })
        real = {'chicken_chettinad', 'boondi_raita', 'wheat_chapati',
                'soya_keema'}
        for p in out['pairings']:
            assert set(p['dishes']) <= real

    def test_a_raising_rule_does_not_take_the_day_down(self):
        broken = {'veg_dry': {'name': 'x', 'richness_score': object()}}
        out = build_pairings(broken)
        assert isinstance(out['pairings'], list)
