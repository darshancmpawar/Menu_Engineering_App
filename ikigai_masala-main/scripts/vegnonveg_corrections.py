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
  * `matar` / `mutter` does NOT imply vegetarian either. **Keema Matar is the
    meat dish** — the peas are what is added to the mince, not what replaces
    it. So the word settles nothing in either direction, and a rule keyed on it
    would have flipped rows at random. `mutter_keema` was held back as
    non-veg on exactly that reasoning and then resolved by the CLIENT, who
    confirmed their dish is peas keema; the soya rows were resolved by the
    ontology contradicting itself.

That is the shape of the whole exercise: the name narrows the question and
never answers it.

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
        # Client verdict: this is MATAR keema — peas keema — not the Mughlai
        # mutton dish the name also describes. It was the one row the dish name
        # could not settle (the peas in "Keema Matar" are added to the mince,
        # not substituted for it), so it was left non-veg and reported; the
        # kitchen has now said which dish it makes. Filed with `gobi_keema_
        # mutter`, the other minced-vegetable keema, rather than with the soya
        # family — the peas are the dish, not a soya stand-in.
        'mutter_keema': ('veg_dry', 'mixed_veg_dry', 'green_peas', 'green_peas'),
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
        # Client verdict: chicken, non-veg DRY. Kastoori Kebab is a kasoori-
        # methi chicken kebab, and `kasturia_kebab` is the same dish already
        # filed chicken in this city — this row's `key_ingredient: besan` and
        # `sub_category: pakora_/_bajji` were the mapping pipeline reading it as
        # a gram-flour fritter, which is what kept it in the veg starter pool.
        # Mangalorean CHICKEN curry — in Tulu `kori` is chicken and `gassi` is
        # curry. It sat in `veg_gravy` with no protein beside `chicken_gassi`,
        # which is the same dish correctly filed. Neither of the other two
        # detection channels could reach it: its name shares no letters with
        # `chicken_gassi`, so string similarity scored ~0.5, and `kori` is not a
        # word any English/Hindi meat list carries. What found it was grouping
        # dishes by a SYNONYM-normalised key — `kori|gassi` and `chicken|gassi`
        # collapse to one dish — which is worth keeping as a channel.
        'kori_gassi': ('nonveg_main', 'chicken_south_coastal',
                       'chicken', 'is_nonveg_gravy'),
        'kasturi_kebab': ('nonveg_main', 'chicken_spicy_fry',
                          'chicken', 'is_nonveg_dry'),
        # Client verdict: both are non-veg. Awadhi minced-meat kebabs, and the
        # protein is `mutton` because that is what both dishes ARE — shami is
        # minced beef/lamb/mutton with ground chana dal, galouti (Tunday) is
        # minced mutton. Flagged in the report rather than silently chosen:
        # `mutton` puts them in a 2-dish pool that Stripe's mutton window and
        # cap select on, where `chicken` would put them in a 498-dish one. One
        # line to flip if the kitchen makes them with chicken.
        'shami_kebab':   ('nonveg_main', 'chicken_spicy_fry',
                          'mutton', 'is_nonveg_dry'),
        'gauloti_kebab': ('nonveg_main', 'chicken_spicy_fry',
                          'mutton', 'is_nonveg_dry'),
    },
    'hyderabad': {
        'kolkata_chic_curry': ('nonveg_main', 'chicken_north_masala',
                               'chicken', 'is_nonveg_gravy'),
        'kasturi_kebab': ('nonveg_main', 'chicken_spicy_fry',
                          'chicken', 'is_nonveg_dry'),
        'kori_gassi':    ('nonveg_main', 'chicken_south_coastal',
                          'chicken', 'is_nonveg_gravy'),
        'shami_kebab':   ('nonveg_main', 'chicken_spicy_fry',
                          'mutton', 'is_nonveg_dry'),
        'gauloti_kebab': ('nonveg_main', 'chicken_spicy_fry',
                          'mutton', 'is_nonveg_dry'),
    },
}

# --------------------------------------------------------------------------
# 2b. Rows the client asked to be removed.
#     A removal is the one step the correction chain cannot undo, so nothing
#     lands here without the client saying so — these two did.
# --------------------------------------------------------------------------
_SALAD_BAR = ('onion_rings_carrots_batons_chinese_cabbage_english_cucumber_'
              'bell_pepper_tomato_quarters_boiled_chana_boiled_peanuts_'
              'boiled_rajma_corn_boiled_betroot_')

# --------------------------------------------------------------------------
# 2c. One dish, one name — for the duplicates THIS work uncovered.
#
# `canonical_dish_spellings.py` is the usual home for "one dish, one spelling"
# and these are deliberately not there. It runs at chain step 3 and this runs at
# 8c, and the winner of each fold below can only be chosen once the veg verdict
# is known: folding `kori_gassi` into `chicken_gassi` at step 3 means picking
# between two rows without yet knowing that one of them is on the wrong side of
# the vegetarian line. Every pair here is the same dish under a synonym, a
# truncation or a typo — not two spellings of one word, which is what that
# script's word-level `CANONICAL_SPELLINGS` handles.
#
# `FOLD_DROPS` maps loser -> winner; the loser's `client` pool tokens are folded
# into the winner first, so no client silently loses a dish it makes.
# `FOLD_RENAMES` is for the survivor whose own spelling is the minority one.
# --------------------------------------------------------------------------
FOLD_DROPS = {
    'bangalore': {
        # `kasturia_kebab` is the corruption; Kastoori/Kasturi is the dish. The
        # surviving row is the one this script just corrected, so it is also the
        # better-attributed of the two (`kasturia_kebab` has no sub_category).
        'kasturia_kebab': 'kasturi_kebab',
        # `kori` is Tulu for chicken, so `kori_gassi` and `chicken_gassi` are
        # one dish. The English protein word wins the name — it is the one a
        # reader of the menu and every other row in the file uses.
        'kori_gassi': 'chicken_gassi',
        # "chic" is `chicken` truncated by whatever wrote the row.
        'kolkata_chic_curry': 'kolkata_chicken_curry',
    },
    'hyderabad': {
        'kasturia_kebab': 'kasturi_kebab',
        'kori_gassi': 'chicken_gassi',
        'kolkata_chic_curry': 'kolkata_chicken_curry',
    },
    'ncr': {
        # Four spellings of chilli chicken. `chilly_chicken` is the attributed
        # one and survives (renamed below); the typo goes. `chilli_chicken_fry`
        # and `chilli_chicken_gravy` are NOT folded in — a dry and a gravy are
        # different dishes, which is the distinction the whole exercise turns on.
        'chilli_chiken': 'chilly_chicken',
        # Two spellings of one dish and no correctly-spelled twin in NCR, so one
        # survives and is renamed below.
        'honey_chilli_chiciken': 'honey_chilli_checken',
    },
}

FOLD_RENAMES = {
    'ncr': {
        'chilly_chicken': 'chilli_chicken',
        'honey_chilli_checken': 'honey_chilli_chicken',
        # NCR carries `tandoori_chicken_masala` and
        # `tandoori_chicken_seekh_masala` but no plain tandoori chicken, so this
        # is a rename rather than a fold — the dish is not a duplicate of either.
        'tandoori_chcien': 'tandoori_chicken',
    },
}

REMOVALS = {
    'bangalore': {
        # Not a dish: a whole salad BAR written as one row, 160 characters of
        # components. Two of them — one ending `boiled_eggs` (filed
        # `nonveg_main`, so the bar was a candidate for the day's meat dish)
        # and one ending `paneer_cubes`. A menu printing either is unreadable
        # and no colour, ingredient or variety rule can reason about it.
        _SALAD_BAR + 'boiled_eggs': 'a salad bar, not a dish',
        _SALAD_BAR + 'paneer_cubes': 'a salad bar, not a dish',
        # No protein, no sub_category, no key_ingredient, and both cities
        # already list explicit veg biryanis while Hyderabad lists the chicken
        # one. A misspelling of "hyderabadi dum biryani" carrying nothing that
        # says which it is.
        'hederabad_dum_biryani': 'junk duplicate of hyderabadi_dum_biryani',
    },
    'hyderabad': {
        _SALAD_BAR + 'boiled_eggs': 'a salad bar, not a dish',
        _SALAD_BAR + 'paneer_cubes': 'a salad bar, not a dish',
        'hederabad_dum_biryani': 'junk duplicate of hyderabadi_dum_biryani',
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
    ('mutter_keema', 'ncr', 'RESOLVED -> veg (peas keema)',
     'The client confirmed it is MATAR keema - peas keema - not the Mughlai '
     'mutton dish the name also describes. Now veg_dry / green_peas.'),
    ('kasturi_kebab', 'bangalore,hyderabad', 'RESOLVED -> chicken, non-veg dry',
     'Confirmed chicken. It duplicates kasturia_kebab, already filed chicken in '
     'both cities - the name fold is in canonical_dish_spellings.py.'),
    ('shami_kebab', 'bangalore,hyderabad', 'RESOLVED -> non-veg, protein=mutton',
     'Confirmed non-veg. Protein set to mutton, which is what the dish is '
     '(minced beef/lamb/mutton with ground chana dal). NOTE: this takes '
     "Bangalore's mutton pool from 2 dishes to 4, and Stripe's mutton window "
     'and weekly cap select on that pool. One line to flip to chicken if the '
     'kitchen makes it that way.'),
    ('gauloti_kebab', 'bangalore,hyderabad', 'RESOLVED -> non-veg, protein=mutton',
     'Confirmed non-veg. Galouti (Tunday) is a Lucknawi minced-MUTTON kebab. '
     "Same pool note as shami_kebab."),
    ('veg_keema_matar / veg_keema_mutter', 'ncr', 'RESOLVED -> veg, soya',
     'Client confirmed vegetarian and soya-based, which is what was applied.'),
    ('hederabad_dum_biryani', 'bangalore,hyderabad', 'RESOLVED -> removed',
     'Confirmed junk duplicate of hyderabadi_dum_biryani.'),
    ('onion_rings_...boiled_eggs / ...paneer_cubes', 'bangalore,hyderabad',
     'RESOLVED -> removed',
     'Confirmed: a salad BAR written as one 160-character row, not a dish. '
     'Both variants removed; the boiled-eggs one was filed nonveg_main, so the '
     'bar was a candidate for the day\'s meat dish.'),
    ('honey_chilli_checken + honey_chilli_chiciken', 'ncr',
     'non-veg; name fold pending',
     'Both are now chicken, so neither can reach a vegetarian. They are two '
     'spellings of one dish with no correctly-spelled twin in NCR - the fold to '
     'a single canonical name is handled by canonical_dish_spellings.py.'),
    ('chilli_chiken', 'ncr', 'non-veg; name fold pending',
     'Now chicken. NCR also lists chilly_chicken, chilli_chicken_fry and '
     'chilli_chicken_gravy; the spelling fold is in canonical_dish_spellings.py.'),
    ('tandoori_chcien', 'ncr', 'non-veg; name fold pending',
     'Now chicken. Folds to tandoori_chicken.'),
    ('kolkata_chic_curry', 'bangalore,hyderabad', 'non-veg; name fold pending',
     'Now chicken. Folds to kolkata_chicken_curry, the same dish already '
     'correctly filed in both cities.'),
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

    # Folds next, now that both rows of each pair are on the right side of the
    # line. Client tokens move to the winner before the loser goes.
    folds = FOLD_DROPS.get(city, {})
    if folds:
        lower = df['item'].map(_norm)
        by_name = {v: i for i, v in lower.items()}
        drop_idx = []
        for loser, winner in folds.items():
            if loser not in by_name or winner not in by_name:
                continue
            li, wi = by_name[loser], by_name[winner]
            if 'client' in df.columns:
                tokens = set()
                for side in (df.at[wi, 'client'], df.at[li, 'client']):
                    tokens |= {t.strip() for t in str(side or '').split(',')
                               if t.strip() and t.strip().lower() != 'nan'}
                df.at[wi, 'client'] = ','.join(sorted(tokens))
            drop_idx.append(li)
            changes.append(f'{loser}: FOLDED into {winner}')
        if drop_idx:
            df = df.drop(index=drop_idx).reset_index(drop=True)

    lower = df['item'].map(_norm)
    for old, new in FOLD_RENAMES.get(city, {}).items():
        hit = df.index[lower == old]
        if not len(hit) or (lower == new).any():
            continue
        df.at[hit[0], 'item'] = new
        changes.append(f'{old}: RENAMED to {new}')

    # Removals last, so a row cannot be corrected and then dropped in one pass
    # — the changes list would report a fix that is not in the file.
    drop = REMOVALS.get(city, {})
    if drop:
        gone = df.index[df['item'].map(_norm).isin(drop)]
        for i in gone:
            changes.append(f'{_norm(df.at[i, "item"])}: REMOVED '
                           f'({drop[_norm(df.at[i, "item"])]})')
        df = df.drop(index=gone).reset_index(drop=True)

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
