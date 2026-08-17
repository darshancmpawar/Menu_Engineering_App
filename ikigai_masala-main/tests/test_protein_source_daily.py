"""A protein source on the plate every day (Tekion / Stryker, Bangalore).

The client supplied a list of protein sources — choley, rajma, kala chana,
lobia, the moong/masoor/urad/toor/chana dal family, sprouts, soya, paneer,
tofu, besan chilla, peanut chaat, khichdi, ghugni — and wants at least one of
them on the menu every day, anywhere across flavoured rice, veg gravy, veg dry,
salad or dal.

Two pieces had to exist for that to be expressible:

* **`daily_min`** on `selector_frequency` — the twin of `daily_max`. `min`
  counts days across the horizon, so `min: 5` means "5 of 5" on a week but
  "5 of 10" on a fortnight; `daily_min` means "every day" regardless.
* **`base_slot` as a list** — the constraint spans five slots, and scoping it to
  any single one would be a different rule.

The selector is on `key_ingredient` because that is how the client specified it,
which is also why `scripts/protein_key_ingredients.py` folds the variant
spellings: a dish whose column says `channa_dal` or `cottage_cheese` is exactly
what was asked for but invisible to a `key_ingredient` selector.
"""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.protein_key_ingredients import (
    FOLD,
    PROTEIN_KEY_INGREDIENTS,
    REGIONAL_PULSES,
    fold,
)
from src.menu_rules.selector_frequency_rule import SelectorFrequencyRule
from src.ontology.paths import city_excel_path

SLOTS = ['rice', 'veg_gravy', 'veg_dry', 'salad', 'dal']


def _norm(s):
    return str(s).strip().lower()


@pytest.fixture(scope='module')
def blr():
    df = pd.read_excel(city_excel_path('Bangalore'))
    df.columns = [c.strip() for c in df.columns]
    return df


# --------------------------------------------------------------------------
# The vocabulary fix
# --------------------------------------------------------------------------

def test_variant_spellings_are_gone(blr):
    """Each folded value named a dish the client asked for, under another name."""
    ki = set(blr['key_ingredient'].map(_norm))
    for variant in FOLD:
        assert variant not in ki, f'{variant} should have been folded'


def test_folded_dishes_now_carry_a_listed_protein(blr):
    names = blr['item'].map(_norm)
    expected = {
        'cholar_dalna': 'chana_dal',
        'amti_channa_dal': 'chana_dal',
        'soppu_moong_palya': 'green_moong',
        'allesande_kalu_palya': 'black_eyed_pea',
        'paruppu_urundai_kuzhambu': 'toor_dal',
    }
    for item, want in expected.items():
        rows = blr[names == item]
        assert len(rows) == 1, f'{item}: expected 1 row, got {len(rows)}'
        assert _norm(rows.iloc[0]['key_ingredient']) == want


def test_every_fold_target_is_on_the_clients_list():
    """Folding into a value the rule does not select for would be pointless."""
    for variant, canonical in FOLD.items():
        assert canonical in PROTEIN_KEY_INGREDIENTS, (variant, canonical)


def test_regional_pulses_are_left_alone(blr):
    """horse_gram / avarekalu / broad beans are real pulses but are NOT variant
    spellings of anything on the client's list. Renaming them to make a rule
    fire would misname the dish; they stay, opted out, for the client to decide."""
    ki = set(blr['key_ingredient'].map(_norm))
    assert any(p in ki for p in REGIONAL_PULSES), 'expected some to still exist'
    for p in REGIONAL_PULSES:
        assert p not in PROTEIN_KEY_INGREDIENTS


def test_fold_is_idempotent(blr):
    out = blr.copy()
    assert fold(out) == 0, 're-running the fold changed rows again'


def test_the_five_slots_all_carry_protein_sources(blr):
    """A rule spanning the five slots needs each of them to be able to help."""
    ct = blr['course_type'].map(_norm)
    ki = blr['key_ingredient'].map(_norm)
    for slot in SLOTS:
        n = int((ct.eq(slot) & ki.isin(PROTEIN_KEY_INGREDIENTS)).sum())
        assert n > 0, f'{slot} has no protein-source dish at all'


# --------------------------------------------------------------------------
# The two rule-engine additions
# --------------------------------------------------------------------------

def _rule(**cfg):
    base = {'type': 'selector_frequency', 'name': 't',
            'selector': {'key_ingredient': 'paneer'}}
    base.update(cfg)
    return SelectorFrequencyRule(base)


def test_daily_min_alone_is_a_valid_config():
    r = _rule(daily_min=1)
    assert r.validate_config(), r.validation_errors()


def test_daily_min_rejects_a_negative():
    assert not _rule(daily_min=-1).validate_config()


def test_base_slot_accepts_a_list_and_a_string():
    one = _rule(daily_min=1, base_slot='veg_gravy')
    assert one.base_slots == {'veg_gravy'}
    assert one.base_slot == 'veg_gravy', 'single-slot configs must be unchanged'

    many = _rule(daily_min=1, base_slot=SLOTS)
    assert many.base_slots == set(SLOTS)
    assert many.base_slot is None, 'a multi-slot rule has no single slot'


def test_base_slot_omitted_still_means_every_slot():
    assert _rule(daily_min=1).base_slots is None


# --------------------------------------------------------------------------
# The wiring
# --------------------------------------------------------------------------

@pytest.mark.parametrize('client,slug', [('Tekion', 'tekion'),
                                         ('Stryker', 'stryker')])
def test_the_rule_is_configured_and_valid(client, slug):
    from src.menu_rules.menu_rule_loader import MenuRuleLoader
    loader = MenuRuleLoader()
    rules = loader.load_for_client(
        client, loader.load_for_city('Bangalore'), 'Counter 1')
    got = [r for r in rules if r.name == f'{slug}_protein_source_daily']
    assert got, f'{slug}_protein_source_daily is not loaded for {client}'
    r = got[0]
    assert r.validate_config(), r.validation_errors()
    assert r.daily_min == 1
    assert r.base_slots == set(SLOTS)


def test_the_selector_matches_only_listed_key_ingredients(blr):
    """A row matches iff its key_ingredient is on the client's list — no name
    or flag fallback, because the client specified the constraint in terms of
    key ingredients."""
    from src.menu_rules.menu_rule_loader import MenuRuleLoader
    loader = MenuRuleLoader()
    rules = loader.load_for_client(
        'Tekion', loader.load_for_city('Bangalore'), 'Counter 1')
    r = [x for x in rules if x.name == 'tekion_protein_source_daily'][0]
    ct = blr['course_type'].map(_norm)
    sub = blr[ct.isin(SLOTS)]
    matched = sub[[r._row_matches(row) for _, row in sub.iterrows()]]
    got = set(matched['key_ingredient'].map(_norm))
    assert got <= set(PROTEIN_KEY_INGREDIENTS), got - set(PROTEIN_KEY_INGREDIENTS)
    assert len(matched) > 500, f'only {len(matched)} dishes matched'
