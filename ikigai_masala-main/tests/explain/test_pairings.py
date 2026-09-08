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
