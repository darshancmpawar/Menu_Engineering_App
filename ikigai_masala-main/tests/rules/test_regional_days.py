"""Regional theme days: the measurement, the scope key, and the rules built.

Three things have to hold, and each fails differently and quietly if it does
not:

* **A region is a FLOOR, never a filter.** Bangalore holds zero Punjabi rice and
  zero Punjabi bread; narrowing those slots empties them, which is
  `Chain rules/ncr_south_bread.py`'s incident. So the floor's slot list is derived
  from the region's own measured depth, and a slot the region cannot fill is
  simply not in it.
* **`only_on_dates` scopes, it does not ban.** `allowed_day_types` forbids the
  selector on days it does not list; this must say NOTHING about them. Getting
  that backwards would turn "serve three Tamil dishes on Thursday" into "serve
  no Tamil food Monday to Wednesday".
* **The regional columns are absent from every committed workbook**, so every
  entry point has to answer "no regions" rather than raise. Nothing about the
  product may change until the data lands.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest
from ortools.sat.python import cp_model

from src.application.regions import (
    normalize_region_map, region_rule_configs, resolve_region_days,
)
from src.menu_rules.selector_frequency_rule import SelectorFrequencyRule, _iso_day
from src.menu_rules.soft_preference_rule import SoftPreferenceRule
from src.ontology.regions import (
    MIN_REGION_SLOTS, SLOT_DISH_FLOOR, Region, has_region_data,
    measure_regions, region_by_name, themeable,
)


# --------------------------------------------------------------------------
# A synthetic city list. The real columns only exist in the client's corrected
# workbooks, which are not installed, so the measurement is tested against a
# frame built to the same shape rather than against a file that has none.
# --------------------------------------------------------------------------
def _rows(region, admin, cuisine, per_slot):
    out = []
    for slot, n in per_slot.items():
        for i in range(n):
            out.append({
                'item': f'{region.lower().replace(" ", "_")}_{slot}_{i}',
                'course_type': slot, 'cuisine_family': cuisine,
                'state_origin': region, 'admin_type': admin,
            })
    return out


def _frame():
    rows = []
    # Deep everywhere — a full regional day.
    rows += _rows('Tamil Nadu', 'state', 'south_indian', {
        'rice': 9, 'veg_gravy': 9, 'veg_dry': 9, 'dal': 9, 'sambar': 9, 'bread': 5})
    # Deep in five, and holds NO rice and NO bread at all. This is Punjab's real
    # shape in Bangalore and the reason the floor cannot be a filter.
    rows += _rows('Punjab', 'state', 'north_indian', {
        'veg_gravy': 9, 'veg_dry': 6, 'dal': 7, 'nonveg_main': 8, 'dessert': 4})
    # Below MIN_REGION_SLOTS — offered greyed, never themeable.
    rows += _rows('Goa', 'state', 'north_indian', {'veg_gravy': 5, 'rice': 4})
    # A pan-level bucket: filled, and not a region. Must never be offered.
    rows += _rows('Pan-North India', 'non_state', 'north_indian', {
        'rice': 40, 'veg_gravy': 40, 'veg_dry': 40, 'dal': 40, 'bread': 40})
    rows += _rows('Europe (foreign)', 'foreign', 'continental', {'veg_gravy': 20})
    return pd.DataFrame(rows)


@pytest.fixture(scope='module')
def regions():
    return measure_regions(_frame())


# --------------------------------------------------------------------------


class TestTheColumnGatesOnAdminTypeOnly:
    """`state_confidence` is `high` on 9 Bangalore rows and 0 Pune ones, and
    `region_authority` has no UNRESOLVED bucket at all in Pune or Hyderabad
    while Bangalore is 66% of it. Neither is comparable across cities, so
    `admin_type` is the gate."""

    def test_a_pan_level_bucket_is_not_a_region(self, regions):
        names = {r.name for r in regions}
        assert 'Pan-North India' not in names
        assert 'Europe (foreign)' not in names

    def test_real_states_are_found_with_their_depth(self, regions):
        tn = region_by_name(regions, 'Tamil Nadu')
        assert tn is not None
        assert tn.slot_counts['sambar'] == 9
        assert set(tn.deep_slots) == {'rice', 'veg_gravy', 'veg_dry', 'dal',
                                      'sambar', 'bread'}

    def test_a_slot_under_the_floor_is_not_deep(self):
        r = Region('X', frozenset({'south_indian'}),
                   {'rice': SLOT_DISH_FLOOR - 1, 'dal': SLOT_DISH_FLOOR})
        assert r.deep_slots == ('dal',)

    def test_a_thin_region_is_measured_but_not_themeable(self, regions):
        goa = region_by_name(regions, 'Goa')
        assert goa is not None, 'a thin region must still be reported'
        assert not goa.is_themeable
        assert goa not in themeable(regions)

    def test_lookup_tolerates_case_and_spacing(self, regions):
        """Exact-match-only is the shape of note 9's silent `clients.name`
        mismatch: it loads as zero rules while /plan still answers 200."""
        assert region_by_name(regions, '  tamil nadu ').name == 'Tamil Nadu'
        assert region_by_name(regions, 'Nowhere') is None


class TestAWorkbookWithoutTheColumns:
    """A city whose list has not been given `state_origin` / `admin_type` yet.
    Every committed workbook used to be in this state; none is now."""

    def test_has_region_data_is_false(self):
        assert not has_region_data(pd.DataFrame([{'item': 'a', 'course_type': 'rice'}]))

    def test_measuring_yields_nothing_rather_than_raising(self):
        assert measure_regions(pd.DataFrame([{'item': 'a'}])) == ()


class TestTheFeatureIsLive:
    """It is not any more. The corrected workbooks carry `state_origin` and
    `admin_type`, so every shipped city can be themed — this is the test that
    said so when it switched on, kept as the assertion that it stays on."""

    @pytest.mark.parametrize('city', ['bangalore', 'chennai', 'hyderabad',
                                      'ncr', 'pune'])
    def test_every_shipped_city_can_be_themed(self, city):
        from src.ontology.repository import OntologyRepository
        df, _ = OntologyRepository().menu_data(city)
        assert has_region_data(df)
        usable = [r for r in measure_regions(df) if r.usable_slots()]
        assert usable, f'{city} carries the columns but no region clears the floor'

    def test_a_region_is_a_floor_and_never_a_filter(self):
        """The load-bearing decision, re-measured against the real data rather
        than restated.

        No region in any city comes close to covering the plate: the best of
        them, Karnataka in Bangalore, can fill 12 of the 22 base slots, and most
        manage three to nine. Nobody's regional cooking supplies a curd side and
        a rasam and a welcome drink — so a region applied as a FILTER empties
        every slot it does not reach, and applied as a FLOOR it fills what it
        can and leaves the rest to the city's own list. Half the plate is the
        margin here, not a rounding error.
        """
        from src.constants import BASE_SLOT_NAMES
        from src.ontology.repository import OntologyRepository
        best = 0
        for city in ('bangalore', 'chennai', 'ncr', 'pune'):
            df, _ = OntologyRepository().menu_data(city)
            for region in measure_regions(df):
                covered = set(region.usable_slots())
                if covered:
                    assert covered < set(BASE_SLOT_NAMES), (city, region.name)
                    best = max(best, len(covered))
        assert best < len(BASE_SLOT_NAMES)


class TestTheRepositoryCacheDoesNotDeadlock:
    """`OntologyRepository.regions` must not hold `self._lock` while calling
    `menu_data()`, which takes the same lock. `threading.Lock` is not
    reentrant, so the first version of this hung every request on a cache miss
    — and hung it *silently*, which is why a plain timing assertion is worth
    having: nothing raises, the endpoint simply never answers.
    """

    def test_a_cold_read_completes(self):
        import threading
        from src.ontology.repository import OntologyRepository

        repo = OntologyRepository()
        done = threading.Event()

        def _read():
            repo.regions('bangalore')
            done.set()

        t = threading.Thread(target=_read, daemon=True)
        t.start()
        assert done.wait(timeout=120), \
            'regions() did not return — the lock is being taken twice'

    def test_a_warm_read_is_cached(self):
        from src.ontology.repository import OntologyRepository
        repo = OntologyRepository()
        first = repo.regions('bangalore')
        assert repo.cache_sizes()['regions'] == 1
        assert repo.regions('bangalore') is first

    def test_reset_clears_it(self):
        from src.ontology.repository import OntologyRepository
        repo = OntologyRepository()
        repo.regions('bangalore')
        repo.reset()
        assert repo.cache_sizes()['regions'] == 0


class TestTheFloorIsDerivedFromDepth:
    """Punjab's floor runs over gravy/dry/dal/non-veg/dessert. Rice and bread
    are not in it, so it is always satisfiable and a relaxation keeps meaning
    one thing: the pool ran out THIS WEEK."""

    def test_a_region_with_no_rice_gets_a_floor_without_rice(self, regions):
        pb = region_by_name(regions, 'Punjab')
        assert 'rice' not in pb.usable_slots()
        assert 'bread' not in pb.usable_slots()
        assert set(pb.usable_slots()) == {'veg_gravy', 'veg_dry', 'dal',
                                          'nonveg_main', 'dessert'}

    def test_the_floor_is_capped_to_the_slots_this_counter_serves(self, regions):
        pb = region_by_name(regions, 'Punjab')
        assert pb.floor_for(['veg_gravy', 'dal']) == 2
        assert pb.floor_for(['veg_gravy']) == 1
        assert pb.floor_for(['rice', 'bread']) == 0

    def test_a_counter_serving_none_of_them_yields_no_rule(self, regions):
        pb = region_by_name(regions, 'Punjab')
        assert region_rule_configs({'2026-09-25': pb}, ['rice', 'bread']) == []


class TestThemeCompatibilityIsDerived:
    """Every southern state is 100% `south_indian` and every northern one 100%
    `north_indian`, so the matrix comes from the workbook and cannot drift."""

    def test_a_south_region_fits_south_and_mix(self, regions):
        tn = region_by_name(regions, 'Tamil Nadu')
        assert tn.compatible_with('south')
        assert tn.compatible_with('mix')
        assert not tn.compatible_with('north')

    @pytest.mark.parametrize('theme', ['chinese', 'continental', 'biryani'])
    def test_a_flag_narrowed_theme_takes_no_region(self, regions, theme):
        """Those themes narrow by flag, not by cuisine, so a region's dishes are
        removed before any floor could be read."""
        for r in regions:
            assert not r.compatible_with(theme)

    def test_the_alternating_meta_theme_takes_no_region_either(self, regions):
        """`chinese_continental` resolves per ISO-week parity to chinese or
        continental, and NEITHER takes a region. It has to be listed
        explicitly: an unlisted theme reads as "narrows nothing", so leaving it
        out offered every region on a day whose main slots are flag-narrowed to
        Chinese food."""
        for r in regions:
            assert not r.compatible_with('chinese_continental')

    def test_every_shipped_theme_has_a_verdict(self, regions):
        """The guard on the above: a theme added to AVAILABLE_THEMES without a
        THEME_CUISINES entry silently becomes region-friendly."""
        from src.client.client_config import AVAILABLE_THEMES
        from src.ontology.regions import THEME_CUISINES
        assert set(AVAILABLE_THEMES) <= set(THEME_CUISINES)

    def test_an_unknown_theme_narrows_nothing(self, regions):
        """A theme the filter does not narrow by cuisine leaves every dish in
        the pool, so a region genuinely can be served — allowing it is correct.
        The UI is stricter (it offers nothing it has no verdict for), which is
        the safe asymmetry."""
        assert region_by_name(regions, 'Punjab').compatible_with('holiday')


class TestResolvingTheTwoInputs:
    DATES = [dt.date(2026, 9, 21) + dt.timedelta(days=i) for i in range(5)]
    THEMES = ['mix', 'chinese', 'biryani', 'south', 'north']

    def _resolve(self, regions, **kw):
        return resolve_region_days(self.DATES, self.THEMES, regions, **kw)

    def test_a_weekday_map_lands_on_the_right_date(self, regions):
        chosen, problems = self._resolve(regions, region_map={'thu': 'Tamil Nadu'})
        assert list(chosen) == ['2026-09-24']
        assert not problems

    def test_both_weekday_spellings_work(self, regions):
        a, _ = self._resolve(regions, region_map={'thursday': 'Tamil Nadu'})
        b, _ = self._resolve(regions, region_map={'thu': 'Tamil Nadu'})
        assert list(a) == list(b)

    def test_a_per_date_pick_beats_the_weekly_pattern(self, regions):
        """On Monday, which is `mix` and so admits either region — the
        precedence has to be visible without a theme conflict deciding it."""
        chosen, problems = self._resolve(
            regions, region_map={'mon': 'Tamil Nadu'},
            region_days={'2026-09-21': 'Punjab'})
        assert chosen['2026-09-21'].name == 'Punjab'
        assert not problems

    def test_an_empty_per_date_pick_clears_the_pattern_for_that_day(self, regions):
        """Unsetting a day on screen has to be expressible, or the standing
        pattern could never be dropped for one week."""
        chosen, _ = self._resolve(
            regions, region_map={'thu': 'Tamil Nadu'}, region_days={'2026-09-24': ''})
        assert chosen == {}

    def test_a_theme_conflict_is_reported_not_silently_dropped(self, regions):
        chosen, problems = self._resolve(
            regions, region_days={'2026-09-25': 'Tamil Nadu'})   # Friday is north
        assert chosen == {}
        assert problems[0]['reason'] == 'theme_conflict'
        assert 'Tamil Nadu' in problems[0]['message']

    def test_a_chinese_day_is_reported_too(self, regions):
        _, problems = self._resolve(regions, region_days={'2026-09-22': 'Punjab'})
        assert problems[0]['reason'] == 'theme_conflict'

    def test_a_thin_region_is_refused_with_its_count(self, regions):
        _, problems = self._resolve(regions, region_days={'2026-09-21': 'Goa'})
        assert problems[0]['reason'] == 'too_thin'
        assert str(MIN_REGION_SLOTS) in problems[0]['message']

    def test_an_unknown_region_is_refused(self, regions):
        _, problems = self._resolve(regions, region_days={'2026-09-21': 'Atlantis'})
        assert problems[0]['reason'] == 'unknown'

    def test_a_date_outside_the_horizon_is_ignored_quietly(self, regions):
        """Not an error: a standing pattern legitimately names days this plan
        does not cover, and a stale pick from a previous horizon is noise."""
        chosen, problems = self._resolve(
            regions, region_days={'2030-01-01': 'Tamil Nadu'})
        assert chosen == {} and problems == []

    def test_a_mix_day_accepts_either_region(self, regions):
        chosen, _ = self._resolve(regions, region_days={'2026-09-21': 'Punjab'})
        assert chosen['2026-09-21'].name == 'Punjab'


class TestNormalizingAStoredMap:
    def test_unknown_days_and_regions_are_dropped(self, regions):
        got = normalize_region_map(
            {'thu': 'Tamil Nadu', 'someday': 'Punjab', 'fri': 'Atlantis'}, regions)
        assert got == {'thursday': 'Tamil Nadu'}

    def test_a_thin_region_cannot_be_stored(self, regions):
        assert normalize_region_map({'mon': 'Goa'}, regions) == {}

    def test_the_canonical_spelling_is_what_is_stored(self, regions):
        assert normalize_region_map({'mon': 'tamil nadu'}, regions) == {
            'monday': 'Tamil Nadu'}

    def test_junk_is_not_a_map(self, regions):
        assert normalize_region_map(None, regions) == {}
        assert normalize_region_map(['thu'], regions) == {}


class TestTheGeneratedRules:
    def test_one_pair_per_region_not_per_date(self, regions):
        tn = region_by_name(regions, 'Tamil Nadu')
        cfgs = region_rule_configs({'2026-09-24': tn, '2026-10-01': tn})
        assert len(cfgs) == 2
        assert {c['type'] for c in cfgs} == {'selector_frequency', 'soft_preference'}
        assert cfgs[0]['only_on_dates'] == ['2026-09-24', '2026-10-01']

    def test_both_rules_are_valid_and_scoped(self, regions):
        tn = region_by_name(regions, 'Tamil Nadu')
        floor, prefer = region_rule_configs({'2026-09-24': tn})
        hard = SelectorFrequencyRule(floor)
        soft = SoftPreferenceRule(prefer)
        assert hard.validate_config(), hard.validation_errors()
        assert soft.validate_config(), soft.validation_errors()
        assert hard.only_on_dates == {'2026-09-24'}
        assert soft.only_on_dates == {'2026-09-24'}

    def test_the_soft_half_is_low_tier(self, regions):
        """Above freshness in a cell, below every real rule — a regional day
        must never cost a colour, a protein or a client's own frequency."""
        tn = region_by_name(regions, 'Tamil Nadu')
        _, prefer = region_rule_configs({'2026-09-24': tn})
        assert prefer['priority'] == 'low'

    def test_the_selector_is_the_state_column(self, regions):
        tn = region_by_name(regions, 'Tamil Nadu')
        floor, _ = region_rule_configs({'2026-09-24': tn})
        assert floor['selector'] == {'state_origin': 'Tamil Nadu'}


class TestTheStateOriginSelector:
    def test_it_matches_a_row(self):
        m = SelectorFrequencyRule._parse_matcher({'state_origin': 'Tamil Nadu'})
        assert SelectorFrequencyRule._matches(
            pd.Series({'state_origin': 'Tamil Nadu'}), m)
        assert not SelectorFrequencyRule._matches(
            pd.Series({'state_origin': 'Punjab'}), m)

    def test_admin_type_is_selectable_too(self):
        m = SelectorFrequencyRule._parse_matcher({'admin_type': 'state'})
        assert SelectorFrequencyRule._matches(pd.Series({'admin_type': 'state'}), m)
        assert not SelectorFrequencyRule._matches(
            pd.Series({'admin_type': 'non_state'}), m)

    def test_a_blank_cell_does_not_match(self):
        """`_norm_cell`, not `_norm_str(str(...))` — note 37. A NaN read through
        `str()` becomes the value 'nan' and every unclassified row groups under
        it."""
        m = SelectorFrequencyRule._parse_matcher({'state_origin': 'nan'})
        assert not SelectorFrequencyRule._matches(
            pd.Series({'state_origin': float('nan')}), m)


class TestOnlyOnDatesScopesAndDoesNotBan:
    """The distinction this whole key turns on."""

    @pytest.mark.parametrize('raw,want', [
        (dt.date(2026, 9, 24), '2026-09-24'),
        ('2026-09-24', '2026-09-24'),
        ('2026-09-24T00:00:00', '2026-09-24'),
        ('not a date', ''), ('', ''), (None, ''),
    ])
    def test_date_parsing(self, raw, want):
        assert _iso_day(raw) == want

    def test_an_unparseable_date_makes_the_rule_inert_not_universal(self):
        """The safe direction for a scope key: a typo costs the rule, it does
        not silently apply it to every day."""
        r = SelectorFrequencyRule({
            'name': 'r', 'selector': {'flag': 'f'}, 'daily_min': 1,
            'only_on_dates': ['garbage']})
        assert r.only_on_dates is None or r.only_on_dates == set()

    def _solve(self, only_on_dates):
        """Two days, one cell each, two candidates; a `daily_min` on the flag."""
        model = cp_model.CpModel()
        dates = [dt.date(2026, 9, 24), dt.date(2026, 9, 25)]
        cells, picks = [], []
        for di in range(2):
            rows = [pd.Series({'item': f'hit_{di}', 'is_x': 1}),
                    pd.Series({'item': f'miss_{di}', 'is_x': 0})]
            xs = [model.NewBoolVar(f'x_{di}_0'), model.NewBoolVar(f'x_{di}_1')]
            model.Add(sum(xs) == 1)
            cells.append(type('C', (), {
                'd_idx': di, 'base_slot': 'rice', 'slot_id': 'rice__1',
                'date': dates[di], 'cand_rows': rows, 'x_vars': xs})())
            picks.append(xs)

        def link_any(m, lits, y):
            if not lits:
                m.Add(y == 0)
                return
            m.Add(sum(lits) >= y)
            for lit in lits:
                m.Add(lit <= y)

        cfg = {'name': 'r', 'selector': {'flag': 'is_x'}, 'base_slot': 'rice',
               'daily_min': 1}
        if only_on_dates is not None:
            cfg['only_on_dates'] = only_on_dates
        SelectorFrequencyRule(cfg).apply(
            model, {}, None,
            {'cells': cells, 'dates': dates, 'day_types': ['mix', 'mix'],
             'link_any_fn': link_any})
        # Push the solver AWAY from the flagged dish, so a day only carries it
        # when the floor forces it to.
        model.Maximize(sum(x[1] for x in picks))
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 5
        assert solver.Solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        return [bool(solver.Value(x[0])) for x in picks]

    def test_unscoped_it_binds_every_day(self):
        assert self._solve(None) == [True, True]

    def test_scoped_it_binds_only_the_listed_day(self):
        assert self._solve(['2026-09-24']) == [True, False]

    def test_the_unlisted_day_is_not_banned_merely_unconstrained(self):
        """If `only_on_dates` banned instead of scoping, day 2's flagged dish
        would be forbidden rather than simply unrequired. Maximising TOWARD it
        proves the difference."""
        model = cp_model.CpModel()
        dates = [dt.date(2026, 9, 24), dt.date(2026, 9, 25)]
        rows = [pd.Series({'item': 'hit', 'is_x': 1}),
                pd.Series({'item': 'miss', 'is_x': 0})]
        xs = [model.NewBoolVar('a'), model.NewBoolVar('b')]
        model.Add(sum(xs) == 1)
        cell = type('C', (), {
            'd_idx': 1, 'base_slot': 'rice', 'slot_id': 'rice__1',
            'date': dates[1], 'cand_rows': rows, 'x_vars': xs})()

        def link_any(m, lits, y):
            m.Add(sum(lits) >= y) if lits else m.Add(y == 0)
            for lit in lits:
                m.Add(lit <= y)

        SelectorFrequencyRule({
            'name': 'r', 'selector': {'flag': 'is_x'}, 'base_slot': 'rice',
            'daily_min': 1, 'only_on_dates': ['2026-09-24'],
        }).apply(model, {}, None,
                 {'cells': [cell], 'dates': dates, 'day_types': ['mix', 'mix'],
                  'link_any_fn': link_any})
        model.Maximize(xs[0])
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 5
        solver.Solve(model)
        assert bool(solver.Value(xs[0])), \
            'the out-of-scope day must be free to serve the dish, not banned'


class TestTheGeneratedRulesActuallyChangeThePlate:
    """Validating is not working. These run the configs `region_rule_configs`
    emits through CP-SAT and read the dishes back off the solution."""

    SLOTS = ('veg_gravy', 'veg_dry', 'dal', 'nonveg_main', 'dessert')

    def _model(self, region, isos, dates):
        """Two days, five slots, each offering one regional and one ordinary
        dish. Objective pushes AWAY from the regional dish, so any that survive
        were put there by the rules."""
        model = cp_model.CpModel()
        cells, ordinary = [], []
        for di, _ in enumerate(dates):
            for slot in self.SLOTS:
                rows = [
                    pd.Series({'item': f'{slot}_{di}_regional',
                               'state_origin': region.name,
                               'admin_type': 'state', 'course_type': slot}),
                    pd.Series({'item': f'{slot}_{di}_plain',
                               'state_origin': 'Pan-North India',
                               'admin_type': 'non_state', 'course_type': slot}),
                ]
                xs = [model.NewBoolVar(f'{slot}_{di}_r'),
                      model.NewBoolVar(f'{slot}_{di}_p')]
                model.Add(sum(xs) == 1)
                ordinary.append(xs[1])
                cells.append(type('C', (), {
                    'd_idx': di, 'base_slot': slot, 'slot_id': f'{slot}__1',
                    'date': dates[di], 'cand_rows': rows, 'x_vars': xs})())

        def link_any(m, lits, y):
            if not lits:
                m.Add(y == 0)
                return
            m.Add(sum(lits) >= y)
            for lit in lits:
                m.Add(lit <= y)

        ctx = {'cells': cells, 'dates': dates,
               'day_types': ['mix'] * len(dates), 'link_any_fn': link_any}
        terms = []
        for cfg in region_rule_configs({i: region for i in isos},
                                       list(self.SLOTS)):
            rule = (SelectorFrequencyRule(cfg)
                    if cfg['type'] == 'selector_frequency'
                    else SoftPreferenceRule(cfg))
            rule.apply(model, {}, None, ctx)
            if hasattr(rule, 'get_objective_terms'):
                terms.extend(rule.get_objective_terms(model, ctx) or [])
        # Every ordinary dish is worth 1; the soft regional preference is worth
        # far more per day, so it should still win where nothing forbids it.
        model.Maximize(sum(ordinary) + sum(terms))
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 10
        assert solver.Solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        picked = {0: [], 1: []}
        for cell in cells:
            for var, row in zip(cell.x_vars, cell.cand_rows):
                if solver.Value(var):
                    picked[cell.d_idx].append(row['state_origin'])
        return picked

    def test_the_scoped_day_comes_out_regional(self, regions):
        pb = region_by_name(regions, 'Punjab')
        dates = [dt.date(2026, 9, 24), dt.date(2026, 9, 25)]
        picked = self._model(pb, ['2026-09-24'], dates)
        assert sum(1 for p in picked[0] if p == 'Punjab') >= 3, \
            'the floor must put at least three regional dishes on the day'

    def test_the_unscoped_day_is_left_alone(self, regions):
        """The objective prefers ordinary dishes, and with no rule scoped to
        day 2 nothing should push back. If `only_on_dates` leaked, this day
        would come out regional too."""
        pb = region_by_name(regions, 'Punjab')
        dates = [dt.date(2026, 9, 24), dt.date(2026, 9, 25)]
        picked = self._model(pb, ['2026-09-24'], dates)
        assert all(p != 'Punjab' for p in picked[1])

    def test_the_soft_half_carries_the_day_past_the_floor(self, regions):
        """The floor is 3 of 5; the preference should take the rest, which is
        what makes the day READ regional rather than merely contain three
        regional dishes."""
        pb = region_by_name(regions, 'Punjab')
        dates = [dt.date(2026, 9, 24), dt.date(2026, 9, 25)]
        picked = self._model(pb, ['2026-09-24'], dates)
        assert sum(1 for p in picked[0] if p == 'Punjab') == 5

    def test_a_region_with_no_dish_for_a_slot_never_empties_it(self, regions):
        """The load-bearing property. Punjab has no rice in Bangalore; the
        floor must simply not mention rice, and the cell must still fill."""
        pb = region_by_name(regions, 'Punjab')
        cfgs = region_rule_configs({'2026-09-24': pb},
                                   list(self.SLOTS) + ['rice', 'bread'])
        for cfg in cfgs:
            assert 'rice' not in cfg['base_slot']
            assert 'bread' not in cfg['base_slot']


class TestTheSoftHalfRefusesToLookScopedWhenItIsNot:
    def test_prefer_daily_accepts_it(self):
        r = SoftPreferenceRule({
            'name': 'x', 'mode': 'prefer_daily', 'selector': {'flag': 'f'},
            'only_on_dates': ['2026-09-24']})
        assert r.validate_config(), r.validation_errors()

    @pytest.mark.parametrize('mode', ['avoid_consecutive', 'prefer_day_types'])
    def test_another_mode_rejects_it(self, mode):
        """Silently ignoring it would be a rule that reads date-scoped and is
        not — the failure this whole key exists to avoid."""
        r = SoftPreferenceRule({
            'name': 'x', 'mode': mode, 'selector': {'flag': 'f'},
            'day_types': ['north'], 'only_on_dates': ['2026-09-24']})
        assert not r.validate_config()
        assert any('only_on_dates' in e for e in r.validation_errors())
