"""Dishes filed on the wrong side of the vegetarian line.

**all cities.** The veg/non-veg boundary is the one ontology error with a
consequence outside the software. `PoolBuilder._nonveg_mask` reads
`primary_protein` and `is_egg_dish`, and it decides two different things:

  * a row it marks non-veg is dropped from every slot except `nonveg_main` /
    `nonveg_soup`, so a **vegetarian dish marked non-veg** disappears from the
    pool it belongs to and is served, if at all, as the day's meat dish;
  * a row it marks veg stays in the veg pools, so a **meat dish marked veg** is
    plated to someone who asked not to be served meat.

Neither shows up as an error. Both plate.

**Why this is not `nonveg_structural_flags.py` or `misspelled_protein_names.py`.**
Those two ask "what FORM is this non-veg dish" and "is this row's name a typo of
a protein". This asks the prior question — is the dish non-veg at all — and the
answer is not in the row. It is in what the dish IS, which is why every verdict
below was settled by looking the dish up rather than by matching its name.

**The method, and why a name pattern is not it.** A token rule over these names
gets them wrong in both directions, and the two traps sit next to each other:

  * `keema` does NOT imply meat. Soya keema, nutri keema (Nutrela soya
    granules, sold as "nutri nuggets" / "meal maker") and gobi keema are
    standard vegetarian North Indian dishes — minced soya or cauliflower
    standing in for mince. Eleven NCR rows and one in Bangalore/Hyderabad.
  * `matar` / `mutter` does NOT imply vegetarian. **Keema Matar is the meat
    dish** — the peas are what is added to the mince, not what replaces it. So
    `mutter_keema` is left alone while `soya_matar_keema` is corrected, and a
    rule keyed on either word would have flipped exactly the wrong one.

Same shape for `bhurji`, which means *scrambled* and not *egg*: paneer, palak-
chana and mooli bhurji are vegetarian, and NCR filed all three under the
vendor's `egg_items` heading.

**The source bank agreed with none of this and cannot be appealed to.** The
enriched workbooks carry `primary_protein__source: original` and
`__band: verified` on every row here — "verified" there means the pass RETAINED
the incoming value, not that anyone checked it. It also files the family
inconsistently: `soya_keema_mutter` is `soy` / `veg_dry` and `soya_matar_keema`
is `mutton` / `nonveg_main`, the same dish twice. That self-contradiction is the
ontology's own evidence and is why the corrections below point where they do.

**The other direction is a misspelling problem**, and the same one
`misspelled_protein_names.py` documented: a typo hides a meat dish from every
check that reads the name, INCLUDING the vendor's own categorisation.
`tandoori_chcien` was filed by the source bank as
`vegetable_north_indian_curry` / `paneer_curry`, so nothing downstream had a
reason to doubt it. Four NCR rows and two shared by Bangalore/Hyderabad were
sitting in veg pools.

Corrections are **conservative in the direction that matters**: a dish whose
status is genuinely arguable is left non-veg and reported, because a vegetarian
dish withheld is a menu that is worse, and a meat dish served is a promise
broken. What is reported rather than applied goes to
`docs/vegnonveg_to_confirm.csv`.

Idempotent; re-run after any re-import. `tests/data/test_vegnonveg_corrections.py`.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling scripts
from city_list import CITIES  # noqa: E402

_ROOT = Path(__file__).resolve().parent.parent
_ITEMS = _ROOT / 'data' / 'raw' / 'city_items'
_REPORT = _ROOT / 'docs' / 'vegnonveg_to_confirm.csv'

# Every column that marks a row non-veg. A correction to the veg side has to
# clear all of them: `_nonveg_mask` reads `primary_protein` and `is_egg_dish`,
# but the form flags drive the composition rules, so a row left with
# `is_nonveg_gravy` would still be picked by `nonveg_main_daily_pair`.
NONVEG_FLAGS = (
    'is_egg_dish', 'is_seafood', 'is_fish_dish', 'is_nonveg_starter',
    'is_nonveg_gravy', 'is_south_chicken_gravy', 'is_north_chicken_gravy',
    'is_chinese_chicken_gravy', 'is_nonveg_dry', 'is_tandoor_nonveg_dry',
    'is_nonveg_biryani', 'is_deep_fried_nonveg_dry', 'is_semidry_nonveg_main',
    'is_continental_chicken_gravy', 'is_continental_chicken_dry',
)

# --------------------------------------------------------------------------
# 1. Vegetarian dishes filed as non-veg.
#    (course_type, sub_category, primary_protein, key_ingredient)
#    Every target value is one the same city already uses for the dish's
#    nearest correctly-filed sibling, so nothing new enters the vocabulary.
# --------------------------------------------------------------------------
VEG_CORRECTIONS = {
    'ncr': {
        # Minced SOYA, not meat. `primary_protein: mutton` on all eleven is one
        # bad fuzzy match on "keema", propagated across the family. The target
        # values are NCR's own: `soya_keema` and `soya_keema_mutter` are already
        # veg_dry / chole_and_soya_dry / soy, and `soya_keema` was corrected on
        # its own in `course_type_corrections.py` — this is that fix finished.
        'bhuna_soya_keema':        ('veg_dry', 'chole_and_soya_dry', 'soy', 'soya'),
        'bhuna_soya_keema_masala': ('veg_dry', 'chole_and_soya_dry', 'soy', 'soya'),
        'mutter_soya_keema':       ('veg_dry', 'chole_and_soya_dry', 'soy', 'soya'),
        'pudhina_soya_keema':      ('veg_dry', 'chole_and_soya_dry', 'soy', 'soya'),
        'soya_matar_keema':        ('veg_dry', 'chole_and_soya_dry', 'soy', 'soya'),
        # "Nutri" / "nutrela" / "nutree" is the soya-granule brand used as the
        # generic word for the ingredient, the way "meal maker" is.
        'nutri_keema':             ('veg_dry', 'chole_and_soya_dry', 'soy', 'soya'),
        'nutri_keema_corn':        ('veg_dry', 'chole_and_soya_dry', 'soy', 'soya'),
        'nutri_keema_veg':         ('veg_dry', 'chole_and_soya_dry', 'soy', 'soya'),
        'nutree_keema_matar':      ('veg_dry', 'chole_and_soya_dry', 'soy', 'soya'),
        # `veg_keema_*` names its own side. A veg keema is soya, paneer,
        # mushroom or lentil depending on the kitchen; `soy` follows the eleven
        # siblings it arrived beside, and is listed in the report as the one
        # value here chosen by family rather than by the dish's own name.
        'veg_keema_matar':         ('veg_dry', 'chole_and_soya_dry', 'soy', 'soya'),
        'veg_keema_mutter':        ('veg_dry', 'chole_and_soya_dry', 'soy', 'soya'),
        # `bhurji` is "scrambled", not "egg". All three came in under the source
        # bank's `egg_items` heading, which is where the egg protein came from.
        'paneer_bhurji':           ('veg_gravy', 'paneer_curry', 'paneer', 'paneer'),
        'palak_chana_bhurji':      ('veg_gravy', 'lentil_and_beans_curry',
                                    'chickpea', 'chickpea'),
        # Baby potato and white radish. No protein focus, so the column stays
        # blank — the value a veg dish of roots legitimately has.
        'banarasi_baby_aloo_muli_ki_bhurji': ('veg_dry', 'aloo_root_veg_dry',
                                              '', 'potato'),
    },
    'bangalore': {
        # Minced cauliflower with peas — vegan, and nothing about it is chicken.
        # `gobi_matar` in NCR is the same dish and is veg_dry / mixed_veg_dry.
        'gobi_keema_mutter': ('veg_dry', 'mixed_veg_dry', 'green_peas', 'gobi'),
    },
    'hyderabad': {
        'gobi_keema_mutter': ('veg_dry', 'mixed_veg_dry', 'green_peas', 'gobi'),
    },
}

# --------------------------------------------------------------------------
# 2. Non-veg dishes sitting in a vegetarian pool.
#    (course_type, sub_category, primary_protein, flag_to_set)
#    Re-filed rather than deleted: a removal is the one step the correction
#    chain cannot undo, and whether a near-duplicate should also go is a menu
#    decision — every one of these is reported alongside its correctly-spelled
#    twin in `docs/vegnonveg_to_confirm.csv`.
# --------------------------------------------------------------------------
NONVEG_CORRECTIONS = {
    'ncr': {
        # "chcien" / "chiken" / "checken" / "chiciken" are the same typo class
        # as `chciken` / `chivken` in `misspelled_protein_names.py`, and they
        # defeat the same checks — including the source bank's own, which filed
        # `tandoori_chcien` as `vegetable_north_indian_curry` / `paneer_curry`.
        'tandoori_chcien':      ('nonveg_main', 'chicken_north_masala',
                                 'chicken', 'is_nonveg_dry'),
        # Carried `is_chinese_veg_gravy`, so it was not merely sitting in the
        # veg pool — it was eligible for a themed Chinese VEG gravy cell.
        'chilli_chiken':        ('nonveg_main', 'chicken_chinese_gravy',
                                 'chicken', 'is_nonveg_gravy'),
        'honey_chilli_checken': ('nonveg_main', 'chicken_chinese_gravy',
                                 'chicken', 'is_nonveg_gravy'),
        'honey_chilli_chiciken': ('nonveg_main', 'chicken_chinese_gravy',
                                  'chicken', 'is_nonveg_gravy'),
    },
    'bangalore': {
        # "chic" truncated, not a dish word. `kolkata_chicken_curry` is the same
        # dish correctly filed in the same city.
        'kolkata_chic_curry': ('nonveg_main', 'chicken_north_masala',
                               'chicken', 'is_nonveg_gravy'),
    },
    'hyderabad': {
        'kolkata_chic_curry': ('nonveg_main', 'chicken_north_masala',
                               'chicken', 'is_nonveg_gravy'),
    },
}

# --------------------------------------------------------------------------
# 3. Right side of the veg line, wrong protein.
#    (primary_protein, flags_to_set, flags_to_clear)
#    These stay non-veg. The protein still matters: `ingredient_ban_rule`
#    matches on it, `is_egg_dish` drives every egg-frequency rule a client
#    writes, and a chicken flag on an egg dish is what let ICON Chn's "a
#    chicken gravy on Tuesday" come back as an egg kurma.
# --------------------------------------------------------------------------
PROTEIN_ONLY = {
    'bangalore': {
        # Bengali; `mangsho` is meat and in Bengal that means goat/mutton.
        'kosha_mangsho': ('mutton', (), ()),
        # Telugu `kodi guddu` is "chicken EGG" — the bird qualifies the egg, it
        # is not a second ingredient. Both rows were chicken, and both carried
        # `is_north_chicken_gravy`, so an egg dish was satisfying chicken rules.
        'kodi_guddu_masala':    ('egg', ('is_egg_dish',),
                                 ('is_north_chicken_gravy',)),
        'kothimeera_kodiguddu': ('egg', ('is_egg_dish',),
                                 ('is_north_chicken_gravy',)),
    },
    'hyderabad': {
        'kosha_mangsho': ('mutton', (), ()),
        'kodi_guddu_masala':    ('egg', ('is_egg_dish',),
                                 ('is_north_chicken_gravy',)),
        'kothimeera_kodiguddu': ('egg', ('is_egg_dish',),
                                 ('is_north_chicken_gravy',)),
        # NB `kothmeera_kodikura` is NOT here: `kodi kura` is chicken curry, so
        # coriander-chicken is exactly what it says. Only `kodi guddu` is egg.
    },
}

# --------------------------------------------------------------------------
# 4. Reported, never applied — the verdict is the client's.
#    (cities, what the row says now, the question)
# --------------------------------------------------------------------------
NEEDS_CLIENT_DECISION = [
    ('mutter_keema', 'ncr', 'nonveg_main / mutton',
     'LEFT NON-VEG. "Keema Matar" is the meat dish - the peas are added to the '
     'mince, not substituted for it - so the name reads non-veg even though it '
     'arrived beside eleven veg keemas that were all wrong. Kept as mutton '
     'because withholding a veg dish is cheaper than serving meat by mistake. '
     'Confirm whether NCR intends a second mutton dish beside mutton_curry.'),
    ('kasturi_kebab', 'bangalore,hyderabad', 'starter / no protein / ki=besan',
     'LEFT VEG. Kastoori/Kasturi Kebab is a kasoori-methi CHICKEN kebab, and '
     '`kasturia_kebab` is filed chicken in the same two cities. But this row '
     'says key_ingredient=besan and sub_category=pakora, i.e. a gram-flour '
     'fritter. Either it is a veg namesake (keep) or a duplicate of '
     'kasturia_kebab in the veg starter pool (re-file or remove).'),
    ('shami_kebab', 'bangalore,hyderabad', 'starter / no protein',
     'LEFT VEG. Traditionally minced meat; the vegetarian chana-dal version is '
     'equally standard and is what a veg starter slot would mean. Sitting '
     'beside hara_bhara_kebab and dahi_ke_kebab, which are unambiguously veg.'),
    ('gauloti_kebab', 'bangalore,hyderabad', 'starter / no protein',
     'LEFT VEG. Same question as shami: galouti is a Lucknawi minced-mutton '
     'kebab, and rajma/veg galouti is a common vegetarian version.'),
    ('hederabad_dum_biryani', 'bangalore,hyderabad', 'rice / no protein',
     'LEFT VEG. Misspelling of "hyderabadi dum biryani", which exists in both '
     'chicken and vegetable forms; the row carries no protein, sub_category or '
     'key_ingredient to settle it, and both cities already list explicit veg '
     'biryanis. Likely a junk duplicate - confirm remove.'),
    ('veg_keema_matar / veg_keema_mutter', 'ncr', 'corrected to soy',
     'APPLIED as soy. A "veg keema" may be soya, paneer, mushroom or lentil; '
     'soy follows the eleven siblings it arrived with rather than the dish name. '
     'Confirm the ingredient if the kitchen makes it another way.'),
    ('onion_rings_...boiled_eggs', 'bangalore,hyderabad',
     'nonveg_main / egg',
     'LEFT AS IS. Not a dish - a whole salad BAR written as one row, ending in '
     '"boiled eggs". Correctly non-veg, wrongly a nonveg_main. Belongs with the '
     'self-named-row cleanup, not here.'),
    ('honey_chilli_checken + honey_chilli_chiciken', 'ncr',
     'both re-filed to chicken',
     'APPLIED. Two spellings of ONE dish, and NCR has no correctly-spelled '
     'twin. Both are now non-veg, so neither can be plated to a vegetarian, but '
     'the duplicate remains - confirm which spelling to keep.'),
    ('chilli_chiken', 'ncr', 're-filed to chicken',
     'APPLIED. NCR already lists chilly_chicken, chilli_chicken_fry and '
     'chilli_chicken_gravy - this is a fourth spelling. Confirm remove.'),
    ('tandoori_chcien', 'ncr', 're-filed to chicken',
     'APPLIED. NCR lists tandoori_chicken_masala and '
     'tandoori_chicken_seekh_masala; plain tandoori chicken is arguably a '
     'distinct dish. Confirm keep-and-rename or remove.'),
    ('kolkata_chic_curry', 'bangalore,hyderabad', 're-filed to chicken',
     'APPLIED. kolkata_chicken_curry is the same dish correctly filed in both '
     'cities. Confirm remove.'),
]


def _norm(v) -> str:
    return str(v if v is not None else '').strip().lower()


def _atomic_to_excel(frame: pd.DataFrame, path: Path) -> None:
    """Write via a temp file + rename.

    `to_excel` truncates the target before streaming into it, so an interrupted
    run leaves a 0-byte workbook and the city's item list is gone.
    """
    tmp = path.with_name(path.name + '.tmp')
    frame.to_excel(tmp, index=False)
    tmp.replace(path)


def apply_city(df: pd.DataFrame, city: str) -> tuple[pd.DataFrame, list[str]]:
    """Apply every correction for one city. Pure; returns (frame, changes)."""
    df = df.copy()
    df.columns = [c.strip() for c in df.columns]
    lower = df['item'].map(_norm)
    changes: list[str] = []

    for item, (course, sub, prot, ki) in VEG_CORRECTIONS.get(city, {}).items():
        hit = df.index[lower == item]
        if not len(hit):
            continue
        i = hit[0]
        df.at[i, 'course_type'] = course
        df.at[i, 'sub_category'] = sub
        df.at[i, 'primary_protein'] = prot
        df.at[i, 'key_ingredient'] = ki
        for flag in NONVEG_FLAGS:
            if flag in df.columns:
                df.at[i, flag] = 0
        changes.append(f'{item}: -> VEG ({course}/{sub}, protein={prot or "-"})')

    for item, (course, sub, prot, setflag) in NONVEG_CORRECTIONS.get(city, {}).items():
        hit = df.index[lower == item]
        if not len(hit):
            continue
        i = hit[0]
        df.at[i, 'course_type'] = course
        df.at[i, 'sub_category'] = sub
        df.at[i, 'primary_protein'] = prot
        df.at[i, 'key_ingredient'] = prot
        # A row moving INTO nonveg_main must not keep a veg-side form flag, or
        # it stays eligible for the themed vegetarian cell it was wrongly in.
        for flag in ('is_chinese_veg_gravy', 'is_paneer_gravy', 'is_paneer_fry'):
            if flag in df.columns:
                df.at[i, flag] = 0
        if setflag in df.columns:
            df.at[i, setflag] = 1
        changes.append(f'{item}: -> NON-VEG ({course}/{sub}, protein={prot})')

    for item, (prot, on, off) in PROTEIN_ONLY.get(city, {}).items():
        hit = df.index[lower == item]
        if not len(hit):
            continue
        i = hit[0]
        df.at[i, 'primary_protein'] = prot
        for flag in on:
            if flag in df.columns:
                df.at[i, flag] = 1
        for flag in off:
            if flag in df.columns:
                df.at[i, flag] = 0
        changes.append(f'{item}: protein -> {prot}')

    return df, changes


def write_report() -> None:
    _REPORT.parent.mkdir(parents=True, exist_ok=True)
    with _REPORT.open('w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh)
        w.writerow(['item', 'cities', 'current_state', 'question'])
        for row in NEEDS_CLIENT_DECISION:
            w.writerow(list(row))


def main() -> None:
    total = 0
    for city in CITIES:
        path = _ITEMS / f'{city}.xlsx'
        if not path.exists():
            continue
        df = pd.read_excel(path)
        out, changes = apply_city(df, city)
        if changes:
            _atomic_to_excel(out, path)
            total += len(changes)
            print(f'\n{city}: {len(changes)} correction(s)')
            for c in changes:
                print(f'   {c}')
    write_report()
    print(f'\n{total} correction(s) applied across {len(CITIES)} cities.')
    print(f'{len(NEEDS_CLIENT_DECISION)} question(s) -> {_REPORT.relative_to(_ROOT)}')


if __name__ == '__main__':
    main()
