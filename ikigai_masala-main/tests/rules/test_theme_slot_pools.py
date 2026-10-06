"""What the REST of a themed plate is, and where a south bread may be served.

Two rules, written together because the client asked for them together:

* a Chinese day's **soup, salad and bread** are named outright
  (`slot_pool_by_theme` on `theme_slot_filter`);
* **dosa, idly, uthappam, adai and the akki/ragi rotti family** are served on
  a south day and nowhere else (`south_bread_south_day_only`).

Three failure modes, each of which already happened once here:

1. **The narrowing never runs.** `soup`, `salad` and `starter` are in
   `EXEMPT_FROM_CUISINE`, which is canonical and which a config can only ADD
   to — so a Chinese day served an Indian soup and an Indian salad and nothing
   said so. An explicit per-theme declaration has to beat that exemption, and
   has to RETURN rather than fall through to the Chinese flag map, which would
   narrow bread to Chinese breads, of which every city has none.

2. **The selector matches nothing, or almost nothing** (note 9). Written
   against `is_dosa_family` and `is_rice_bread` alone, this rule moved the
   dosas off a biryani Monday and a mix Wednesday and left `masala_idli` and
   `tri_color_idli` standing in their place: the flags catch 42 of Chennai's
   100 breads and the sub_categories catch 61. A generated week found it; the
   config did not. Hence the guard below walks every branch of the selector
   and fails on a branch that matches no bread row in its own city's list.

3. **The narrowing starves the slot.** NCR's list holds exactly one Chinese
   salad. A two-salad counter narrowed to it is INFEASIBLE on uniqueness while
   one that kept the ordinary pool plans fine — one dish is worse than none,
   the lesson `_combo_variant_cells` already paid for. So the threshold is the
   slot's cell count, and the shortfall is stamped (note 31).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import pathlib

import pandas as pd
import pytest

from src.constants import EXEMPT_FROM_CUISINE
from src.menu_rules.relaxations import RELAXATION
from src.menu_rules.selector_frequency_rule import SelectorFrequencyRule
from src.menu_rules.theme_rules import ThemeSlotFilterRule

CITY_RULES = (pathlib.Path(__file__).resolve().parents[2]
              / 'data' / 'configs' / 'city_rules')


class _Cfg:
    cuisine_col = 'cuisine_family'
    cuisine_south_value = 'south_indian'
    cuisine_north_value = 'north_indian'

    def __init__(self, **counts):
        self.slot_counts = counts


def _rule(**extra):
    return ThemeSlotFilterRule({'name': 'tf', 'type': 'theme_slot_filter',
                                'slot_pool_by_theme': {
                                    'chinese': {'salad': {'cuisine_family': 'chinese'}}},
                                **extra})


def _salads(n_chinese, n_other=4):
    rows = [{'item': f'asian_{i}', 'cuisine_family': 'chinese'}
            for i in range(n_chinese)]
    rows += [{'item': f'kachumber_{i}', 'cuisine_family': 'north_indian'}
             for i in range(n_other)]
    return pd.DataFrame(rows)


DAY = dt.date(2026, 11, 3)


class TestADeclaredPoolBeatsTheExemption:
    def test_salad_is_exempt_from_cuisine_and_narrowed_anyway(self):
        """The reason this rule exists. `salad` is canonically exempt, so the
        theme filter leaves it alone; a declaration is not the filter guessing
        — somebody wrote it down."""
        assert 'salad' in EXEMPT_FROM_CUISINE
        out = _rule().pre_filter_pool(_salads(3), DAY, 'salad', 'chinese',
                                      {'cfg': _Cfg(salad=1)})
        assert set(out['cuisine_family']) == {'chinese'}

    def test_another_theme_is_left_alone(self):
        out = _rule().pre_filter_pool(_salads(3), DAY, 'salad', 'north',
                                      {'cfg': _Cfg(salad=1)})
        assert len(out) == 7

    def test_an_undeclared_slot_is_left_alone(self):
        out = _rule().pre_filter_pool(_salads(3), DAY, 'soup', 'chinese',
                                      {'cfg': _Cfg(soup=1)})
        assert len(out) == 7

    def test_bread_does_not_fall_through_to_the_chinese_flag_map(self):
        """The declaration RETURNS. Falling through would hand the chapatis to
        `_filter_chinese`, which keeps `is_chinese_carb` rows — and no city's
        list has a Chinese bread, so the slot would empty."""
        pool = pd.DataFrame([
            {'item': 'tawa_roti', 'is_plain_phulka_chapathi': 1,
             'is_chinese_carb': 0, 'cuisine_family': 'north_indian'},
            {'item': 'naan', 'is_plain_phulka_chapathi': 0,
             'is_chinese_carb': 0, 'cuisine_family': 'north_indian'},
        ])
        rule = ThemeSlotFilterRule({
            'name': 'tf', 'type': 'theme_slot_filter',
            'slot_pool_by_theme': {
                'chinese': {'bread': {'flag': 'is_plain_phulka_chapathi'}}}})
        out = rule.pre_filter_pool(pool, DAY, 'bread', 'chinese',
                                   {'cfg': _Cfg(bread=1)})
        assert list(out['item']) == ['tawa_roti']


class TestItDegradesRatherThanStarves:
    def test_one_dish_for_two_cells_keeps_the_ordinary_pool(self, caplog):
        """NCR's one Chinese salad, against a two-salad counter."""
        with caplog.at_level(logging.INFO, logger='src.menu_rules'):
            out = _rule().pre_filter_pool(_salads(1), DAY, 'salad', 'chinese',
                                          {'cfg': _Cfg(salad=2)})
        assert len(out) == 5

    def test_one_dish_for_one_cell_is_enough(self):
        out = _rule().pre_filter_pool(_salads(1), DAY, 'salad', 'chinese',
                                      {'cfg': _Cfg(salad=1)})
        assert list(out['item']) == ['asian_0']

    def test_none_at_all_keeps_the_ordinary_pool(self):
        """Chennai: zero Chinese salads in the whole list."""
        out = _rule().pre_filter_pool(_salads(0), DAY, 'salad', 'chinese',
                                      {'cfg': _Cfg(salad=1)})
        assert len(out) == 4

    def test_the_shortfall_is_stamped_for_the_explanation(self, caplog):
        """Unstamped, the record reaches no handler and /plan answers 200 with
        an empty `relaxations` list — a silent relaxation reads exactly like a
        satisfied rule (note 31)."""
        with caplog.at_level(logging.INFO, logger='src.menu_rules'):
            _rule().pre_filter_pool(_salads(0), DAY, 'salad', 'chinese',
                                    {'cfg': _Cfg(salad=1)})
        stamped = [r for r in caplog.records if getattr(r, RELAXATION, None)]
        assert [r.name for r in stamped] == ['src.menu_rules.theme_rules']
        assert getattr(stamped[0], RELAXATION) == 'tf'

    def test_a_missing_slot_count_means_one_cell(self):
        out = _rule().pre_filter_pool(_salads(1), DAY, 'salad', 'chinese',
                                      {'cfg': _Cfg()})
        assert list(out['item']) == ['asian_0']

    def test_a_malformed_declaration_is_ignored_not_crashed(self):
        rule = ThemeSlotFilterRule({
            'name': 'tf', 'type': 'theme_slot_filter',
            'slot_pool_by_theme': {'chinese': ['salad'], 'north': {'salad': {}}}})
        assert rule.slot_pool_by_theme == {}


class TestAllowedDayTypesMayStandAlone:
    def test_a_ban_with_no_count_validates(self):
        """"South bread only on a south day" is a complete rule with no
        frequency in it. Requiring a count meant writing `max: 99`, which reads
        as a cap nobody meant and becomes one on a long enough horizon."""
        rule = SelectorFrequencyRule({
            'name': 'south_bread', 'type': 'selector_frequency',
            'selector': {'flag': 'is_dosa_family'}, 'base_slot': 'bread',
            'allowed_day_types': ['south']})
        assert rule.validation_errors() == []

    def test_a_rule_with_neither_still_fails(self):
        rule = SelectorFrequencyRule({
            'name': 'nothing', 'type': 'selector_frequency',
            'selector': {'flag': 'is_dosa_family'}, 'base_slot': 'bread'})
        assert rule.validation_errors()


# ---------------------------------------------------------------------------
# The configs, against the lists they were written for.
# ---------------------------------------------------------------------------
# Each file is checked against ITS OWN city: `rotis` is akki and ragi roti in
# Bangalore and bhakari in Pune, which is why Pune carries neither rule and
# why a shared guard would be wrong.
OWNERS = [('bangalore', 'Bangalore'), ('chennai', 'Chennai'), ('pune', 'Pune')]


def _rules(city_file):
    return json.loads((CITY_RULES / f'{city_file}.json').read_text())['rules']


def _named(city_file, name):
    return next((r for r in _rules(city_file) if r.get('name') == name), None)


def _breads(city):
    from src.ontology import repository
    df, _ = repository.menu_data(city)
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    mask = df.get('is_bread')
    return df[mask.fillna(0).astype(str).str.strip().str.lower()
              .isin({'1', '1.0', 'true', 'yes'})] if mask is not None else df


def _branches(sel):
    return sel.get('any_of') or [sel]


@pytest.mark.parametrize('city_file,city', OWNERS)
def test_every_south_bread_branch_matches_a_real_dish(city_file, city):
    """Note 9's expensive failure, one branch at a time: a mistyped
    sub_category loads, validates, and bans nothing, while /plan still answers
    200 and the menu still looks fine."""
    rule = _named(city_file, 'south_bread_south_day_only')
    if rule is None:
        pytest.skip(f'{city_file} carries no south-bread rule')
    breads = _breads(city)
    for branch in _branches(rule['selector']):
        m = SelectorFrequencyRule._parse_matcher(branch)
        assert m is not None, f'{branch} parsed to nothing'
        n = sum(1 for _i, r in breads.iterrows()
                if SelectorFrequencyRule._matches(r, m))
        assert n > 0, f'{city}: {branch} matches no bread'


def test_pune_carries_no_south_bread_rule():
    """Deliberate, and the only thing that says so is this test and a comment.
    Pune's list has no dosa, no idly and no uthappam, and its `rotis` rows are
    bajara, jowar and rice BHAKARI — Maharashtrian bread with no business
    being held back for a South Indian day."""
    assert _named('pune', 'south_bread_south_day_only') is None
    sub = _breads('Pune')['sub_category'].astype(str).str.strip().str.lower()
    assert set(_breads('Pune')[sub == 'rotis']['item']) == {
        'bajara_bhakari', 'jowar_bhakari', 'rice_bhakari'}


@pytest.mark.parametrize('city_file,_city', OWNERS)
def test_the_declared_themes_and_slots_are_spelled_right(city_file, _city):
    """Note 9 in its cheapest form. A theme or slot key that matches nothing
    loads silently, narrows nothing, and leaves /plan answering 200 with a
    Chinese day that is not Chinese — there is no other signal."""
    from src.constants import BASE_SLOT_NAMES
    declared = _named(city_file, 'theme_cuisine_filter')['slot_pool_by_theme']
    assert set(declared) == {'chinese'}
    assert set(declared['chinese']) == {'soup', 'salad', 'bread'}
    assert set(declared['chinese']) <= set(BASE_SLOT_NAMES)


@pytest.mark.parametrize('city_file,city', OWNERS)
def test_a_chinese_day_has_a_soup_and_a_bread_to_offer(city_file, city):
    """Chennai has no Chinese SALAD, which is the documented degrade above and
    is not asserted here. A soup and a bread it does have, and so does every
    other city — if one of those ever reads zero the day silently stops being
    Chinese."""
    from src.ontology import repository
    rule = _named(city_file, 'theme_cuisine_filter')
    declared = rule['slot_pool_by_theme']['chinese']
    df, _ = repository.menu_data(city)
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    for slot, flag in (('soup', 'is_soup'), ('bread', 'is_bread')):
        rows = df[df[flag].fillna(0).astype(str).str.strip().str.lower()
                  .isin({'1', '1.0', 'true', 'yes'})]
        m = SelectorFrequencyRule._parse_matcher(declared[slot])
        n = sum(1 for _i, r in rows.iterrows()
                if SelectorFrequencyRule._matches(r, m))
        assert n > 0, f'{city}: no {slot} matches {declared[slot]}'


# ---------------------------------------------------------------------------
# A real week. Every defect above was invisible in the configuration.
# ---------------------------------------------------------------------------
SOUTH_BREAD_SUBS = {
    'classic_dosa', 'masala_/_flavoured_dosa', 'millet-based_dosa',
    'wheat-based_dosa', 'lentil-based_dosa_(adai/pesarattu)', 'uthappam',
    'idli_/_steamed', 'rotis',
}


def _solve(fake_supabase, client):
    from api.app import app
    from tests.client_fixtures import CLIENTS
    fake_supabase.seed('clients', [dict(next(c for c in CLIENTS
                                             if c['name'] == client))])
    app.config['TESTING'] = True
    with app.test_client() as c:
        resp = c.post('/api/v1/plan', json={
            'client_name': client, 'start_date': '2026-11-02',
            'num_days': 5, 'time_limit_seconds': 40})
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()


def _slot_items(day, base):
    """`soup__1` and `soup__2` are both the soup slot."""
    return [v['item_base'] for s, v in day['items'].items()
            if s == base or s.startswith(f'{base}__')]


def _by_item(city):
    from src.ontology import repository
    df, _ = repository.menu_data(city)
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    return {str(r['item']).strip().lower(): r for _i, r in df.iterrows()}


def _south_breads(week, by_item):
    """(iso, day_type, item, sub_category) for every south bread in *week*."""
    out = []
    for iso, day in week.items():
        for item in _slot_items(day, 'bread'):
            sub = str(by_item[item.lower()]['sub_category']).strip().lower()
            if sub in SOUTH_BREAD_SUBS:
                out.append((iso, day.get('day_type'), item, sub))
    return out


def test_a_real_bangalore_week(fake_supabase):
    """Zscaler: a Chinese Friday, a south Thursday, and three days that are
    neither. One solve, read four ways — the dosa this moved off the biryani
    Tuesday is the whole rule, and the dosa still on the Thursday is the half
    that stops it being a plain deletion."""
    week = _solve(fake_supabase, 'Zscaler')['solution']
    blr = _by_item('Bangalore')
    chinese = next(d for d in week.values() if d.get('day_type') == 'chinese')

    for base in ('soup', 'salad'):
        for item in _slot_items(chinese, base):
            fam = str(blr[item.lower()]['cuisine_family']).strip().lower()
            assert fam == 'chinese', f'{base} {item} is {fam}'
    for item in _slot_items(chinese, 'bread'):
        assert int(blr[item.lower()]['is_plain_phulka_chapathi'] or 0) == 1, \
            f'{item} is not a chapati'

    off = [b for b in _south_breads(week, blr) if b[1] != 'south']
    assert not off, f'south bread off a south day: {off}'
    south = next(d for d in week.values() if d.get('day_type') == 'south')
    assert _south_breads({'x': south}, blr), (
        'the south day got no south bread either — a ban that empties both '
        'sides passes the check above and is useless')


def test_a_real_chennai_week(fake_supabase):
    """Gartner. Chennai is where the flags leaked: with `is_dosa_family` and
    `is_rice_bread` alone this same week served `masala_idli` on the biryani
    Monday and `tri_color_idli` on the mix Wednesday."""
    plan = _solve(fake_supabase, 'Gartner')
    off = [b for b in _south_breads(plan['solution'], _by_item('Chennai'))
           if b[1] != 'south']
    assert not off, f'south bread off a south day: {off}'
    # Chennai's list holds no Chinese salad at all, so the Chinese day keeps
    # the ordinary pool. That is the right behaviour and the wrong thing to do
    # silently.
    assert 'theme_cuisine_filter' in {
        r['rule'] for r in (plan.get('relaxations') or [])}


if __name__ == '__main__':      # a runnable check without pytest
    raise SystemExit(pytest.main([__file__, '-q']))
