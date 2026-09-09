"""One dish, one row — applying what `audit_duplicate_dish_names.py` reports.

The audit finds two names for one dish by MEANING rather than spelling
(`aloo_dum` / `dum_aloo`, `bhuna_chicken_masala` / `bhuna_murgh_masala`,
`kori_gassi` / `chicken_gassi`) and has always stopped at a report, because a
merge picks the name that gets PRINTED ON A MENU and 364 of those is not a
decision to take by convention. The client approved all of them, so this is the
apply half.

Three kinds of group, and they need three different things:

  1. **A duplicate.** Every row agrees on `course_type` and `primary_protein`,
     so one row is simply the other written differently. The best-attributed row
     survives under `propose()`'s canonical name and the rest are dropped, with
     their `client` pool tokens folded in so no site loses the dish.

  2. **A misfile** (`MISFILES`). The rows disagree about what the dish IS, so
     one of them is filed wrongly and merging would bury the evidence. These
     need a verdict, and the verdict has to name the SURVIVING ROW rather than
     leave it to `propose()` — `propose()` ranks names, and the better name is
     sometimes on the wrong row. `chana_lauki` (filed `dal`) beats `lauki_chana`
     (filed `veg_dry`) alphabetically, so the mechanical pick would have kept
     the misfiled row and deleted the correct one.

  3. **Two dishes whose names do not say which** (`FORM_RENAMES`). Aloo Beans is
     made as a dry stir-fry AND as an onion-tomato curry; so is Achari Aloo.
     Where BOTH rows are coherently attributed to their own form — one
     `aloo_root_veg_dry` + `is_veg_dry`, the other `aloo_curry` + `is_aloo_gravy`
     — the two filings are independent evidence of two real dishes, not one
     mistake. Deleting either loses a dish a client serves. So the fix is to
     NAME the form, which is this ontology's own convention where it already
     knows both exist: `chilli_paneer_dry` beside `chilli_paneer_gravy`,
     `aloo_methi_dry` beside `aloo_methi`. A form word in the name also splits
     the group for good, because `dish_key` holds `FORM_WORDS` apart from the
     core — that is the distinction the whole audit turns on.

**How a misfile is told from a form pair**, since the two look identical in the
report: is one of the rows a bare IMPORT STUB? A stub has no `sub_category`, no
`is_rule_ready`, and only the generic flag that mirrors its course — the
fingerprint of an importer that had to guess a category from a printed cell. A
guessed course is not evidence that a client served a different form. Where both
rows carry a coherent form-specific `sub_category`, it is.

Two rows break that mechanical test and are argued individually instead, in
their own `reason` below: `chana_lauki`, whose `leafy_dal` is wrong on its face,
and Chennai's `vada_sambar`, which contradicts twelve unanimous siblings.

**Chain position: step 3b, immediately after `canonical_dish_spellings.py`** —
which folds two spellings of one WORD where this folds two names for one DISH.
It belongs there for the reason that one does: every column-correction script
below selects its rows BY NAME. Run it last instead (which is where it started,
next to the audit it consumes) and each of those scripts has already keyed its
verdicts to a name this is about to rename. Twelve of them ended up holding dead
entries that still read as live decisions — `nonveg_structural_flags.ADJUDICATED`
naming `murgh_nizami` after it became `chicken_nizami` — and worse, a verdict
applied to only ONE row of a pair can be silently undone when the fold keeps the
other. Ordering is the fix; a reconciliation pass afterwards is not.

Two things keep it safe this early. The audit still runs at step 16 and must
report 0 groups, which is what catches a later step re-introducing a duplicate.
And the client menu imports at step 7 would otherwise re-mint every dropped
name — each one is still what some client's sheet PRINTS — so
`menu_import._existing_twin` is taught the same `dish_key` lookup, imported from
the audit rather than restated so the fold and the importer cannot drift.

Idempotent: a second pass finds no groups left.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling scripts
from audit_duplicate_dish_names import dish_key, propose  # noqa: E402
from canonical_dish_spellings import COMMON_AT, _has_common_pool  # noqa: E402
from city_list import CITIES  # noqa: E402

_ROOT = Path(__file__).resolve().parent.parent
_ITEMS = _ROOT / 'data' / 'raw' / 'city_items'

#: `(city -> {surviving item: (rename_to | None, reason)})`. The survivor is the
#: correctly-filed row; everything else in its group is dropped. `rename_to` is
#: for the one case where the right row carries the wrong name.
_MISFILES: dict[str, dict[str, tuple]] = {
    'bangalore': {
        'tandoori_achari_aloo': (None, (
            'the `starter` row is a bare stub with no sub_category. The '
            "ontology's own tandoori-aloo sibling `tandoori_aloo_gobi_dry` is a "
            '`veg_dry` under this same `aloo_root_veg_dry`, and a row meant as '
            'a starter would carry `grilled_/_tandoor_starter`, which is what '
            '`tandoori_pineapple` has.')),
        'chilli_baby_corn': (None, (
            'the `veg_gravy` row is a bare stub tagged `north_indian` for an '
            'Indo-Chinese dish. Where this ontology means the gravy it says so '
            '— `chilli_paneer_gravy`, `chilli_gobi_gravy`, '
            '`baby_corn_chilli_milli_semi_gravy` — so a bare name is the dry.')),
        'garlic_butter_vegetables': (None, (
            'vegetables tossed in garlic butter is not a rice dish. The '
            '`healthy_rice` row carries `is_rice` and nothing else.')),
        'lauki_chana': (None, (
            '`leafy_dal` on the other row is wrong on its face — bottle gourd '
            'is not a leaf — so its sub_category is not independent evidence '
            'of a second dish. Both rows say `primary_protein: chickpea`, the '
            'whole legume rather than `chana_dal`, which makes this a sabzi.')),
        'millet_curd_rice': (None, (
            '`is_curd_rice` is what routes a dish to the curd-rice station '
            '(`PoolBuilder` reads the flag, not the course), and the '
            '`healthy_rice` row carries neither it nor a sub_category.')),
        'kadai_veg': (None, (
            'kadai veg is a gravy, and `kadhai` is separately the spelling '
            'SYNONYMS already folds to `kadai`.')),
        'veg_kolhapuri': (None, (
            'veg kolhapuri is a spicy gravy; the `veg_dry` row is a bare stub '
            'carrying only the course mirror.')),
        'lasooni_chana_dal': (None, (
            'the dish is named for chana DAL — the split lentil — and both '
            'rows carry `key_ingredient: chana_dal`, so the other row\'s '
            '`primary_protein: chickpea` (the whole legume) contradicts its '
            'own ingredient column. The mirror image of `lauki_chana`, where '
            'the protein said `chickpea` and nothing said dal.')),
        'aloo_mutter_masala': ('aloo_matar_masala', (
            'the `veg_dry` row is a bare stub — no key_ingredient, no '
            '`is_rule_ready`. Renamed because the surviving row is the one '
            'correctly filed and the dropped one held the better spelling.')),
    },
    'chennai': {
        'sambar_vada': (None, (
            'all twelve other vada rows in Chennai are starters, the soaked '
            'ones included — `curd_vada`, `dahi_vada`, `rasa_vada`, '
            '`mor_kolambu_vada`. The `sambar` row also carries '
            '`key_ingredient: cabbage`, a word absent from its own name.')),
    },
    'ncr': {
        'aloo_gobi_masala': (None, (
            'the other row is filed `north_simple_veg_pulao` with `is_pulao`. '
            'A pulao is a rice dish and this one is not.')),
        'tariwala_aloo': ('aloo_tariwala', (
            '*tariwala* means "with gravy", so the `veg_dry` filing contradicts '
            'the dish\'s own name. Renamed to the dish-first word order the '
            'dropped row used.')),
        'onion_laccha': (None, (
            'laccha pyaz is sliced raw onion served alongside the meal. The '
            '`veg_gravy` filing put it in the cell that holds the day\'s gravy, '
            'and its `key_ingredient: laccha` is the mapping pipeline copying '
            "the name's first word rather than an ingredient.")),
    },
}

#: `(city -> {item to rename: (course_type, new name, reason)})` — the groups
#: where both forms are real dishes. Renaming one side is enough: a `FORM_WORDS`
#: token in the name gives it a different `dish_key`, so the pair never groups
#: again.
#:
#: The row is identified by its COURSE as well as its name, which is what the
#: verdict is actually about — rename *the dry one*. Two things need that. The
#: fold can mint a canonical spelling, so after `aloo_matar` becomes
#: `aloo_matar_dry` the surviving gravy is itself renamed to `aloo_matar`: on a
#: second pass a name-only rule sees both names present and cannot tell "already
#: applied" from "would clobber an unrelated row". And if a later client import
#: mints a *dry* `aloo_achari`, renaming it to `achari_aloo_gravy` would be
#: exactly wrong.
_FORM_RENAMES: dict[str, dict[str, tuple]] = {
    'bangalore': {
        'aloo_matar': ('veg_dry', 'aloo_matar_dry', (
            'three rows: two coherent gravies (`aloo_curry` + `is_aloo_gravy`) '
            'and one coherent dry (`aloo_root_veg_dry` + `is_veg_dry`). The '
            'gravies fold and the dry is named, rather than the other way '
            'round, because aloo matar is a gravy on most menus and the '
            'ontology already spells the exception out — `aloo_methi_dry` sits '
            'beside `aloo_methi`.')),
    },
    'ncr': {
        'aloo_achari': ('veg_gravy', 'achari_aloo_gravy', (
            'achari aloo is made as a dry sabzi and as a creamy onion-tomato '
            'curry, and both rows are filed for their own form — '
            '`aloo_root_veg_dry` against `aloo_curry` + `is_aloo_gravy`.')),
        'adraki_gobi': ('veg_gravy', 'adraki_gobi_gravy', (
            '`mixed_veg_curry` against the other row\'s `mixed_veg_dry`. Both '
            'are coherent, so both are real.')),
        'beans_aloo': ('veg_gravy', 'aloo_beans_gravy', (
            'aloo beans is a Punjabi dry stir-fry and also a light '
            'onion-tomato curry; `mixed_veg_curry` against '
            '`aloo_root_veg_dry`.')),
        'methi_aloo': ('veg_gravy', 'aloo_methi_gravy', (
            'aloo methi is classically dry, which the other row is filed as '
            '(`aloo_root_veg_dry` + `is_leafy_based_dish`); this one is a '
            'coherent `mixed_veg_curry`.')),
    },
}

#: A column on a SURVIVING row that the same evidence condemns. Kept tiny — an
#: attribute gap is `complete_ontology.py`'s job, not this script's.
_FIXES: dict[str, dict[str, dict[str, str]]] = {
    'ncr': {
        # Named by the misfile verdict above: `tariwala` is not an ingredient.
        'aloo_tariwala': {'key_ingredient': 'aloo'},
    },
}

#: Hyderabad is seeded from Bangalore, so it carries the same rows and takes the
#: same verdicts. Mirrored rather than restated so the two cannot drift.
_SEEDED_FROM = {'hyderabad': 'bangalore'}


def _for_city(table: dict, city: str) -> dict:
    return dict(table.get(_SEEDED_FROM.get(city, city), {}))


def _norm(v) -> str:
    s = str(v if v is not None else '').strip()
    return '' if s.lower() in ('', 'nan', 'none', 'nat') else s


def _attribution(row: pd.Series, flag_cols: list[str]) -> tuple:
    """How completely a row is filled in — the merge keeps the fullest.

    A duplicate pair is almost always one attributed master beside one import
    stub, and the stub is the row whose values were guessed. Ranked by
    sub_category first because that is the field an importer never invents.
    """
    flags = sum(1 for c in flag_cols if _norm(row.get(c)) not in ('', '0', '0.0'))
    return (bool(_norm(row.get('sub_category'))),
            _norm(row.get('is_rule_ready')) not in ('', '0', '0.0'),
            sum(1 for v in row.values if _norm(v)),
            flags)


#: Columns a fold must never carry over from a dropped row. The first four are
#: identity, `client` is unioned instead, and `course_type`/`sub_category` are
#: the very thing a misfile verdict just decided — taking them back off the row
#: declared wrong would undo the verdict. `is_*` flags are excluded wholesale
#: because they follow from those two (`complete_ontology.py` derives them).
_NEVER_CARRIED = frozenset({'item', 'item_id', 'client', 'course_type',
                            'sub_category'})


def _carry_unanimous(df: pd.DataFrame, keep: int, idxs: list[int]) -> list[str]:
    """Fill the survivor's BLANK cells from the rows being dropped.

    The rows are the same dish, so a value on any of them is a fact about the
    dish, and dropping the only row that carried it loses data the fold had no
    quarrel with — `tandoori_achari_aloo` survived with a blank
    `key_ingredient` while the row folded into it said `potato`.

    Only where every row that has a value AGREES, which is the test
    `complete_ontology.py` applies to the same question across cities: two
    non-blank values in disagreement are not evidence, and one of them may be an
    importer's guess from the dish name.
    """
    filled = []
    for col in df.columns:
        if col in _NEVER_CARRIED or col.startswith('is_'):
            continue
        if _norm(df.at[keep, col]):
            continue
        values = {_norm(df.at[i, col]) for i in idxs}
        values.discard('')
        if len(values) == 1:
            df.at[keep, col] = values.pop()
            filled.append(col)
    return filled


def _merge_clients(rows: pd.DataFrame, allow_common: bool) -> str:
    """Union the pool tokens, so no site loses a dish to the fold.

    Follows `canonical_dish_spellings._merge_clients`, which had already worked
    this out for the spelling folds — the convention has to be one thing, and a
    plain union broke it two ways. `common` ABSORBS rather than accumulating (a
    dish in the common pool is reachable by every client, so listing five sites
    beside it says nothing), and six or more sites make a dish common in its own
    right, which is the client's own rule and is asserted over the whole
    workbook by `tests/data/test_booking_import.py` — the union put seven sites
    on one row and that test caught it.

    *allow_common* is False where the city HAS no common pool: NCR tags all
    ~1,500 rows to one of eight sites, so promoting there writes a token naming
    no pool that exists.
    """
    tokens: list[str] = []
    for cell in rows['client']:
        for tok in _norm(cell).split(','):
            tok = tok.strip()
            if not tok:
                continue
            if tok.lower() == 'common':
                if allow_common:
                    return 'common'
                continue
            if tok.lower() not in {t.lower() for t in tokens}:
                tokens.append(tok)
    if allow_common and len(tokens) >= COMMON_AT:
        return 'common'
    return ','.join(tokens)


def apply_city(df: pd.DataFrame, city: str,
               settled: Optional[dict] = None) -> tuple[pd.DataFrame, list[str]]:
    """Fold *df* in place-ish; returns the new frame and a log of what changed.

    *settled* is `{dish_key: name}` from the cities already folded, and it keeps
    the city lists from drifting apart. Hyderabad is SEEDED from Bangalore and
    `tests/cities/test_hyderabad_ontology.py` requires it to stay a strict
    superset — but the two lists do not always hold the same duplicates, so the
    fold can legitimately face a group in one city and a single row in the
    other. Hyderabad carried `miloni_sabzi` beside `sabzi_miloni` where
    Bangalore had only the latter, and `propose()`, ranking two equal-length
    names alphabetically, kept `miloni_sabzi`: one dish, two names, one per
    city. That is worse than the duplicate it removed — a `name_contains`
    selector or a shared `constant_items` pin now matches in one city and not
    the other. So a name another city has already settled on wins, whenever it
    is one of the candidates here.
    """
    log: list[str] = []
    flag_cols = [c for c in df.columns if c.startswith('is_')]
    allow_common = _has_common_pool(df)
    lower = df['item'].astype(str).str.lower().str.strip()

    # 1. Name the form, for the groups that are two dishes. Done first so the
    #    renamed row leaves its group before the fold looks at it.
    for old, (course, new, _reason) in sorted(
            _for_city(_FORM_RENAMES, city).items()):
        hit = (lower == old) & (df['course_type'].astype(str).str.strip()
                                .str.lower() == course)
        if not hit.any():
            continue                        # already named, or not this row
        if (lower == new).any():
            raise SystemExit(f'{city}: form rename {old} -> {new} would collide')
        df.loc[hit, 'item'] = new
        lower = df['item'].astype(str).str.lower().str.strip()
        log.append(f'named the form: {old} -> {new}')

    # 2. Re-group and fold.
    misfiles = _for_city(_MISFILES, city)
    groups: dict[tuple, list[int]] = {}
    for idx, name in lower.items():
        groups.setdefault(dish_key(name), []).append(idx)

    drop: list[int] = []
    for key, idxs in sorted(groups.items()):
        names = sorted({lower[i] for i in idxs})
        if len(names) < 2:
            continue
        verdict = [n for n in names if n in misfiles]
        if verdict:
            if len(verdict) > 1:
                raise SystemExit(
                    f'{city}: two verdicts in one group {names} — {verdict}')
            survivor_name = verdict[0]
            rename_to = misfiles[survivor_name][0] or survivor_name
        else:
            courses = {_norm(df.at[i, 'course_type']).lower() for i in idxs}
            proteins = {_norm(df.at[i, 'primary_protein']).lower() for i in idxs}
            proteins.discard('')
            if len(courses) > 1 or len(proteins) > 1:
                # An unadjudicated misfile. Merging would bury the evidence, so
                # it stays split and stays in the report.
                continue
            # The fullest row survives, under the canonical NAME whichever row
            # happened to carry it — unless another city has already settled
            # this dish on one of these names, in which case the cities agreeing
            # matters more than the ranking.
            survivor_name = None
            already = (settled or {}).get(key)
            rename_to = already if already in names else propose(names)

        rows = df.loc[idxs]
        if survivor_name is not None:
            keep = [i for i in idxs if lower[i] == survivor_name][0]
        else:
            keep = max(idxs, key=lambda i: _attribution(df.loc[i], flag_cols))
        df.at[keep, 'client'] = _merge_clients(rows, allow_common)
        carried = _carry_unanimous(df, keep, idxs)
        if _norm(df.at[keep, 'item']).lower() != rename_to:
            df.at[keep, 'item'] = rename_to
        drop += [i for i in idxs if i != keep]
        detail = f' (+{",".join(carried)})' if carried else ''
        log.append(f'{" | ".join(names)} -> {rename_to}{detail}')

    if drop:
        df = df.drop(index=drop).reset_index(drop=True)

    # 3. A SEEDED city agrees with its seed on names, even where there was no
    #    group to fold. Hyderabad is a copy of Bangalore plus Quest's dishes, so
    #    a dish the two spell differently is a divergence rather than a regional
    #    preference — and it only takes one city having the duplicate for the
    #    fold itself to create one. Restricted to `_SEEDED_FROM` on purpose:
    #    NCR names the dish `dum_aloo` where Bangalore says `aloo_dum` and that
    #    is its own list's business, not a drift to correct.
    lower = df['item'].astype(str).str.lower().str.strip()
    if city in _SEEDED_FROM and settled:
        for idx, name in lower.items():
            agreed = settled.get(dish_key(name))
            if not agreed or agreed == name or agreed in set(lower):
                continue
            df.at[idx, 'item'] = agreed
            log.append(f'agreed with {_SEEDED_FROM[city]}: {name} -> {agreed}')
        lower = df['item'].astype(str).str.lower().str.strip()

    # 4. The few column fixes the verdicts named.
    for item, fields in sorted(_for_city(_FIXES, city).items()):
        hit = lower == item
        if not hit.any():
            continue
        for col, value in fields.items():
            if _norm(df.loc[hit, col].iloc[0]) != value:
                df.loc[hit, col] = value
                log.append(f'{item}.{col} = {value}')
    return df, log


def main() -> None:
    total = 0
    # `CITIES` puts the reference city first, which is what makes this work:
    # Bangalore settles a name and Hyderabad, seeded from it, then agrees.
    settled: dict = {}
    for city in CITIES:
        path = _ITEMS / f'{city}.xlsx'
        if not path.exists():
            continue
        df = pd.read_excel(path)
        df.columns = [c.strip() for c in df.columns]
        before = len(df)
        df, log = apply_city(df, city, settled)
        for name in df['item'].astype(str).str.lower().str.strip():
            settled.setdefault(dish_key(name), name)
        if not log:
            print(f'{city}: already folded')
            continue
        df.to_excel(path, index=False)
        total += before - len(df)
        print(f'{city}: {before} -> {len(df)} rows, {len(log)} change(s)')
        for line in log[:6]:
            print(f'    {line}')
        if len(log) > 6:
            print(f'    ... and {len(log) - 6} more')
    print(f'\n{total} duplicate row(s) folded away')


if __name__ == '__main__':
    main()
