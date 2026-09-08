"""One dish written twice — found by meaning, not by spelling. REPORT ONLY.

`canonical_dish_spellings.py` folds two spellings of one WORD (`channa` /
`chana`, `kadhi` / `kadi`). It cannot see two names for one DISH, and the item
lists are full of them:

    aloo_dum            / dum_aloo                    word order
    bhuna_chicken_masala / bhuna_murgh_masala          synonym (murgh = chicken)
    chicken_kali_mirch  / murgh_kalimirchi             both at once
    murgh_razala        / murgh_razeela / murgh_rezalla  three spellings

Every one of these costs the same three things a misspelling costs. `max: 1` on
a weekly rule counts the two names separately, so the dish runs twice.
`unique_items` sees two dishes and lets a plate carry both. And a menu prints
"Dum Aloo" on Monday and "Aloo Dum" on Thursday, which reads to a diner as a
kitchen that is not paying attention.

**Why this was a report and not a correction.** Two reasons, and the second is
the one that mattered:

  * a merge picks a NAME, and these names print on a menu. The mechanical
    choices available here (most cities, most common word order, alphabetical)
    all produce defensible-but-odd results on some rows — `aloo_dum` over
    `dum_aloo` for instance — and 416 of those is not a decision to make by
    convention.
  * **28 of the groups were not duplicates at all.** They disagree about
    `course_type` or `primary_protein`, which means one of the two rows is
    MISFILED and merging would bury the evidence. `chilli_baby_corn` is a
    `veg_dry` beside `baby_corn_chilli` as a `veg_gravy`; `butter_garlic_
    vegetables` is filed `healthy_rice` beside `garlic_butter_vegetables` as a
    `veg_dry`; `dal_rajma` carries `toor_dal` beside `rajma_dal` carrying
    `kidney_bean`. Those needed a verdict, not a fold.

**The client approved every group and every misfile got a verdict**, so
`fold_duplicate_dish_names.py` is now the apply half: 356 duplicate groups
folded (416 rows gone) and 28 adjudicated — 22 by naming the row that survives,
6 by naming the dish's FORM where a dry and a gravy are both real. This audit
therefore reports **0 and 0**, which is the check that the fold converged and
the reason it still runs in the chain (twice: step 3b puts the column
corrections on stable names, step 17 catches what the row-creating steps
re-introduce). A non-zero count here means something upstream minted a
duplicate back.

The counts grew while this was being applied, and each increase was a defect in
the predicate rather than new data: `mutter -> matar` found 17 (`matar_paneer`
was one dish under three names), rewriting PHRASES longest-first found the
`*_kali_mirchi` family that `kali_mirch -> pepper` had been mangling into
`pepperi`, and dropping `and` found the pairs like `carrot_and_beans_poriyal`
that only ever grouped by luck of word order.

This is also a detection channel the other audits do not have, and it has
already earned its place: grouping by a synonym-normalised key is what found
`kori_gassi` — Mangalorean CHICKEN curry (`kori` is Tulu for chicken) sitting in
`veg_gravy` with no protein, beside the correctly-filed `chicken_gassi`. String
similarity scored those two names at ~0.5 and no English or Hindi meat-word list
carries `kori`, so both of the channels in `vegnonveg_corrections.py` missed it.

Writes `docs/duplicate_dish_names.csv`, one row per group, with a proposed
canonical name to approve or edit. `--check` fails if the CSV is stale.
"""

from __future__ import annotations

import collections
import csv
import io
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling scripts
from city_list import CITIES  # noqa: E402

_ROOT = Path(__file__).resolve().parent.parent
_ITEMS = _ROOT / 'data' / 'raw' / 'city_items'
_REPORT = _ROOT / 'docs' / 'duplicate_dish_names.csv'

# Multi-word forms are rewritten first, because a token rule gets them wrong:
# `kodi` alone is Telugu for chicken but `kodi_guddu` is its EGG, and folding
# the phrase to `chicken` would have called two egg dishes chicken.
#
# These targets are GROUPING KEYS, not spellings anybody should serve — `hotsour`
# is not a word — so `propose()` deliberately does not read them. See its
# docstring: PHRASES says two names mean one dish, SYNONYMS says which of two
# words to write, and conflating the two elected `paneer_dopyaza` over
# `paneer_do_pyaza` and `pepper_rasam` over `kali_mirch_rasam`.
PHRASES = {
    'kodi_guddu': 'egg', 'kodiguddu': 'egg',
    'kali_mirch': 'pepper', 'kali_mirchi': 'pepper',
    'kalimirchi': 'pepper', 'kalimirch': 'pepper',
    'do_pyaza': 'dopyaza', 'do_pyaz': 'dopyaza',
    'hot_and_sour': 'hotsour',
}

# Genuine synonyms only — a word for the same thing in another language, or a
# spelling of it. Nothing here changes what the dish IS.
SYNONYMS = {
    # chicken, in the six languages these lists are written in, plus the typos
    'chiken': 'chicken', 'chcien': 'chicken', 'checken': 'chicken',
    'chiciken': 'chicken', 'chick': 'chicken', 'murg': 'chicken',
    'murgh': 'chicken', 'murgir': 'chicken', 'kukkad': 'chicken',
    'kozhi': 'chicken', 'kozi': 'chicken', 'koli': 'chicken',
    'kori': 'chicken', 'kodi': 'chicken', 'pollo': 'chicken',
    # egg / mutton / fish / prawn
    'anda': 'egg', 'ande': 'egg', 'mutta': 'egg', 'guddu': 'egg',
    'muton': 'mutton', 'mangsho': 'mutton', 'gosht': 'mutton',
    'meen': 'fish', 'machli': 'fish', 'machhi': 'fish',
    'jhinga': 'prawn', 'prawns': 'prawn',
    # spelling families the word-level fold does not carry
    'chilly': 'chilli', 'razeela': 'razala', 'rezalla': 'razala',
    'rezala': 'razala', 'haryali': 'hariyali', 'harayali': 'hariyali',
    'chattinad': 'chettinad', 'chettined': 'chettinad',
    'chettiand': 'chettinad', 'makhni': 'makhani', 'makkhani': 'makhani',
    'roghan': 'rogan', 'kadhai': 'kadai',
    # Garlic, four ways, all in the dal slot. The fold made the split visible
    # rather than creating it: Bangalore carried `dal_lasooni`, `dal_lehsooni`
    # and `dal_lehsuni` as three separate pairs, so merging each pair left
    # three rows of one dish — and Citrix's sheet prints a fourth spelling,
    # which the importer then minted as a fifth.
    'lehsooni': 'lasooni', 'lehsuni': 'lasooni', 'lahsoni': 'lasooni',
    'lasuni': 'lasooni', 'lahsuni': 'lasooni',
    # Peas, transliterated two ways in the same city. Bangalore carries 41
    # `matar` names beside 120 `mutter`, NCR 66 beside 24, and the split is what
    # left NCR holding FOUR rows of methi malai peas — `matar_methi_malai`,
    # `methi_matar_malai`, `methi_malai_mutter`, `mutter_methi_malai`. `matar`
    # is the direction because NCR, the North Indian list, prefers it 3:1 for a
    # Hindi word. NB this is a GROUPING fold: it renames a row only where one
    # is already a duplicate of another, so the ~250 rows carrying either
    # spelling are otherwise untouched (that wider vocabulary fold belongs to
    # `canonical_dish_spellings.py`, where a collision gets reviewed one by one).
    'mutter': 'matar',
}

# Words that name the FORM of a dish, kept apart from the core so a dry and a
# gravy of the same ingredients never group together. This is the distinction
# the whole audit turns on: `pepper_chicken_dry` and `pepper_chicken_gravy` are
# two dishes, not one written twice.
FORM_WORDS = frozenset({
    'dry', 'fry', 'roast', 'sukka', 'gravy', 'curry', 'masala', 'semi',
    'biryani', 'pulao', 'rice', 'tikka', 'kebab', 'kabab', 'soup', 'salad',
})

# Connectors that join two ingredients and say nothing about the dish. Dropped
# from the key, so `carrot_and_beans_poriyal` and `beans_carrot_poriyal` are one
# dish — which the ontology already writes both ways, and which the importer's
# similarity path used to catch only because the word order happened to line up.
# Once the fold reordered the surviving name, similarity fell below its cutoff
# and the `and` spelling was minted back as a new row.
CONNECTORS = frozenset({'and'})


def _norm(v) -> str:
    """Lowercased text, with pandas' blank markers read AS blank.

    `str(NaN)` is `'nan'`, which is truthy — so a blank `primary_protein` read
    as a competing value and every blank-vs-filled pair was reported as a
    protein disagreement rather than as the duplicate it is.
    """
    s = str(v if v is not None else '').strip()
    return '' if s.lower() in ('', 'nan', 'none', 'nat') else s.lower()


def dish_key(name: str) -> tuple[str, str]:
    """`(core, form)` — the identity of a dish, word order and language removed.

    `murgh_kalimirchi` and `chicken_pepper` both reduce to `('chicken|pepper',
    '')`. `pepper_chicken_dry` reduces to `('chicken|pepper', 'dry')`, which
    keeps it out of that group.
    """
    text = _norm(name)
    # LONGEST FIRST, because these are substring replacements and one phrase is
    # a prefix of another: `kali_mirch` -> `pepper` fired inside `kali_mirchi`
    # and left `pepperi`, so every `*_kali_mirchi` row silently failed to group
    # with its `kali_mirch` twin. A missed fold rather than a wrong one, which
    # is why it went unnoticed — and the importer then minted the variant back.
    for phrase in sorted(PHRASES, key=len, reverse=True):
        text = text.replace(phrase, PHRASES[phrase])
    tokens = [SYNONYMS.get(t, t) for t in text.split('_')
              if t and t not in CONNECTORS]
    core = sorted(t for t in tokens if t not in FORM_WORDS)
    form = sorted(t for t in tokens if t in FORM_WORDS)
    return '|'.join(core), '|'.join(form)


def _folded_away(name: str) -> int:
    """How many of this name's words SYNONYMS has already canonicalised away.

    The first tiebreak, and the only one that is about correctness rather than
    taste: electing `kadhai_chicken` over `kadai_chicken` would re-instate a
    spelling `canonical_dish_spellings.py` has already folded, so this audit
    would be undoing a committed correction one row at a time. Six of the 313
    proposals did exactly that (`kadhai` x4, `harayali` x2).

    Only SYNONYMS counts. PHRASES is a grouping device whose targets are
    artificial — reading it too picked `paneer_dopyaza` over `paneer_do_pyaza`
    and `chicken_kalimirch` over `chicken_kali_mirch`, i.e. it started deciding
    spellings on the strength of a table that has no opinion about them.
    """
    return sum(1 for t in name.split('_') if t in SYNONYMS)


def canonical_spelling(name: str) -> str:
    """Every word of *name* written the way SYNONYMS says to write it."""
    return '_'.join(SYNONYMS.get(t, t) for t in name.split('_') if t)


def propose(names: list[str]) -> str:
    """The canonical name to suggest, chosen by a stated rule so it is stable.

    In order: fewest words the project has already spelled another way, then a
    name that spells its protein the English way (the word every other row and
    every menu reader uses), then the LONGEST, then alphabetically so two runs
    agree.

    Longest looks odd until you notice that every name in a group carries the
    same words — that is what grouped them — so a length difference is a
    difference in SPELLING, never in content. It is what keeps `egg_do_pyaza`
    over the truncated `egg_do_pyaz` and `bhuna_chicken_masala` over
    `chicken_bhuna`.

    **When EVERY name in the group misspells a word, the winner is written out
    properly rather than elected as-is** — so `aloo_gobi_mutter | gobi_aloo_
    mutter` yields `aloo_gobi_matar` and the five-way `chicken_rezalla | murgh_
    razeela | ...` yields `chicken_razala`. Otherwise a group with no clean
    candidate keeps a spelling the project has already standardised away, which
    is the whole defect `_folded_away` exists to prevent; the ranking would just
    be picking the least-bad of five.

    This is the one case where the answer is not one of the input names, and it
    cannot collide with a row outside the group: canonicalising a word does not
    change `dish_key`, so any row already holding this name would be IN this
    group — and would then have won on `_folded_away` without minting anything.
    """
    def rank(n: str) -> tuple:
        english = any(w in n.split('_') for w in
                      ('chicken', 'egg', 'mutton', 'fish', 'prawn'))
        return (_folded_away(n), not english, -len(n), n)
    best = sorted(names, key=rank)[0]
    return canonical_spelling(best) if _folded_away(best) else best


def collect() -> tuple[list[dict], list[dict]]:
    """Return (duplicates, misfiles) — groups that agree, and groups that do not."""
    groups: dict[tuple, list[tuple]] = collections.defaultdict(list)
    for city in CITIES:
        path = _ITEMS / f'{city}.xlsx'
        if not path.exists():
            continue
        df = pd.read_excel(path)
        df.columns = [c.strip() for c in df.columns]
        for _, row in df.iterrows():
            core, form = dish_key(row['item'])
            groups[(city, core, form)].append(
                (_norm(row['item']), _norm(row['course_type']),
                 _norm(row['primary_protein'])))

    dupes, misfiles = [], []
    for (city, core, form), rows in sorted(groups.items()):
        seen = sorted(set(rows))
        names = sorted({r[0] for r in seen})
        if len(names) < 2:
            continue
        courses = {r[1] for r in seen}
        # A BLANK protein agrees with anything — it is an unfilled cell, not a
        # competing claim. Only two different non-blank values disagree.
        proteins = {r[2] for r in seen if r[2]}
        entry = {
            'city': city, 'dish': core, 'form': form,
            'names': ' | '.join(names),
            'courses': ' | '.join(sorted(courses)),
            'proteins': ' | '.join(sorted(proteins)) or '(blank)',
            'proposed_name': propose(names),
            'rows_removed_if_merged': len(names) - 1,
        }
        if len(courses) == 1 and len(proteins) <= 1:
            dupes.append(entry)
        else:
            entry['why_not_a_merge'] = (
                'course_type disagrees' if len(courses) > 1
                else 'primary_protein disagrees')
            misfiles.append(entry)
    return dupes, misfiles


def write_report(dupes: list[dict], misfiles: list[dict]) -> str:
    """The CSV text. Returned rather than written so `--check` and the test can
    compare against it without a temp file.

    `lineterminator='\n'` is explicit: csv.writer defaults to CRLF, and
    `Path.read_text` normalises that back to LF on the way in, so a report
    written with the default never compares equal to itself.
    """
    cols = ['verdict', 'city', 'dish', 'form', 'names', 'courses', 'proteins',
            'proposed_name', 'rows_removed_if_merged', 'why_not_a_merge']
    rows = [{**d, 'verdict': 'DUPLICATE - approve a name to merge',
             'why_not_a_merge': ''} for d in dupes]
    rows += [{**m, 'verdict': 'MISFILE - needs a verdict, do not merge',
              'proposed_name': ''} for m in misfiles]
    sio = io.StringIO()
    writer = csv.writer(sio, lineterminator='\n')
    writer.writerow(cols)
    writer.writerows([[str(r.get(c, '')) for c in cols] for r in rows])
    return sio.getvalue()


def main() -> None:
    check = '--check' in sys.argv
    dupes, misfiles = collect()
    text = write_report(dupes, misfiles)
    if check:
        current = _REPORT.read_text(encoding='utf-8') if _REPORT.exists() else ''
        if current != text:
            raise SystemExit(
                f'{_REPORT.relative_to(_ROOT)} is stale — re-run '
                f'`python scripts/{Path(__file__).name}`')
        print(f'{_REPORT.relative_to(_ROOT)} is current')
        return
    _REPORT.parent.mkdir(parents=True, exist_ok=True)
    _REPORT.write_text(text, encoding='utf-8')
    removable = sum(d['rows_removed_if_merged'] for d in dupes)
    print(f'{len(dupes)} duplicate group(s) — {removable} row(s) would go')
    print(f'{len(misfiles)} group(s) disagree on course or protein, so one row '
          f'in each is MISFILED — reported, never merged')
    print(f'-> {_REPORT.relative_to(_ROOT)}')


if __name__ == '__main__':
    main()
