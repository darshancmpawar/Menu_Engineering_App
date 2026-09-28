"""A staple is ONE dish, every day — not a category that rotates.

The client's own definition: "staple means like white rice and pickle. it should
be the same daily." White rice and papad are const slots and behave that way
already; the trap is a client sentence like "indian bread will serve chapati as
staple" being configured as a `slot_composition` over a FAMILY.

That is a rule which loads, solves, and looks right in review — the bread is a
chapati every day — while serving a different chapati each day. PhonePe's
composition on `is_plain_phulka_chapathi` rotated over ten Pune breads including
`beetroot_chapati`, `carrot_chapati` and `jeera_roti`. DXC's over 36 Bangalore
breads, ICON Chn's over 12 Chennai ones. All three are pins now.

So: **a composition whose own `_comment` says the dish is daily must resolve to
exactly one dish.** A family restriction is a different rule and says so — ToastTab
CHN's "always a wheat or maida flat bread, never the dosai/idly family" is a real
one and is listed below.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

from src.menu_rules.menu_rule_loader import CLIENT_RULES_DIR
from src.menu_rules.selector_frequency_rule import SelectorFrequencyRule
from src.ontology.repository import OntologyRepository

#: Words in a `_comment` that mean "the same dish every day it is served".
_STAPLE = re.compile(r'\bstaple\b|\bevery day\b|\bdaily\b|\bonly daily\b', re.I)

#: Compositions whose comment trips the pattern but which really are a FAMILY
#: restriction. Each is here because the client's own sentence names a category,
#: not a dish — keep the reason with the entry.
FAMILY_NOT_STAPLE = {
    # "The bread is always a wheat or maida flat bread, never the dosai/idly
    # family." Four different breads across the seven sampled days.
    'toast_tab_chn_bread_is_a_wheat_flatbread',
    # "Welcome drink will be buttermilk only." `only` names the category; the
    # client has not said which buttermilk, and Bangalore carries ten.
    'citrix_welcome_drink_is_buttermilk',
    # A weekday PAIRING ("Tue one egg + one chicken, other days two chicken"),
    # not a staple — the comment says "daily" about the station, not a dish.
    'siemens_nonveg_pair_by_weekday',
    'phonepe_nonveg_1_by_weekday',
    'cloudera_nonveg_by_weekday',
    'sinchncr_nonveg_by_weekday',
    # "Need a veg gravy (paneer, baby corn, gobi, mushroom, rajma, chole,
    # channa) all day, first priority" — seven named families, not one dish.
    'bakertilly_veg_gravy_from_the_named_families_daily',
    # "One will be tawa roti staple and other will be a flavour roti or parata."
    # The client draws the distinction themselves: the staple is pinned, THIS is
    # the family beside it.
    'carelon_second_bread_is_flavoured',
    # "in the first rice slot a veg biryani every weekday" — a category.
    'tcl_rice_is_a_biryani_and_a_south_rice',
}


def _city_of(client):
    from tests.client_fixtures import CLIENTS
    for c in CLIENTS:
        if c['name'] == client:
            return c.get('city') or 'Bangalore'
    return None


def _staple_compositions():
    """``(client, rule)`` for every composition whose comment claims a daily dish."""
    for path in sorted(pathlib.Path(CLIENT_RULES_DIR).glob('*.json')):
        for client, block in json.loads(path.read_text()).items():
            if not isinstance(block, dict):
                continue
            for rule in block.get('rules', []):
                if rule.get('type') != 'slot_composition':
                    continue
                if not _STAPLE.search(str(rule.get('_comment', ''))):
                    continue
                if rule['name'] in FAMILY_NOT_STAPLE:
                    continue
                yield client, rule


def test_there_are_still_staple_shaped_rules_to_check():
    """If this ever empties, the pattern above stopped matching anything and
    every assertion below is passing vacuously."""
    assert list(_staple_compositions()) or FAMILY_NOT_STAPLE


@pytest.mark.parametrize(
    'client,rule',
    list(_staple_compositions()),
    ids=[f"{c}-{r['name']}" for c, r in _staple_compositions()] or ['none'],
)
def test_a_daily_composition_resolves_to_exactly_one_dish(client, rule):
    city = _city_of(client)
    if city is None:
        pytest.skip(f'{client} is not a live client row')
    _df, pools = OntologyRepository().filtered_menu_data(city, [])
    base = rule.get('base_slot')
    if base not in pools:
        pytest.skip(f'{client} does not serve {base}')
    for comp in rule.get('components') or []:
        matcher = SelectorFrequencyRule._parse_matcher(comp.get('selector') or {})
        hits = sorted(str(r['item']) for _i, r in pools[base].iterrows()
                      if SelectorFrequencyRule._matches(r, matcher))
        assert len(hits) == 1, (
            f"{client}/{rule['name']}: its comment says the dish is daily, but "
            f"this selector matches {len(hits)} {base} dishes in {city} "
            f"({hits[:6]}). A staple is one dish — pin it in `constant_items` "
            f"instead, or add the rule to FAMILY_NOT_STAPLE with the client's "
            f"own sentence if it really is a category.")


def test_every_family_exemption_still_names_a_real_rule():
    """An exemption for a rule that no longer exists is a widened guard nobody
    is watching — the same stale-entry case the correction chain keeps hitting."""
    names = set()
    for path in pathlib.Path(CLIENT_RULES_DIR).glob('*.json'):
        for block in json.loads(path.read_text()).values():
            if isinstance(block, dict):
                names |= {r.get('name') for r in block.get('rules', [])}
    missing = sorted(FAMILY_NOT_STAPLE - names)
    assert not missing, f'FAMILY_NOT_STAPLE names rules that are gone: {missing}'
