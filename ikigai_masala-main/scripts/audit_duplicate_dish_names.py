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

**Why this is a report and not a correction.** Two reasons, and the second is
the one that matters:

  * a merge picks a NAME, and these names print on a menu. The mechanical
    choices available here (most cities, most common word order, alphabetical)
    all produce defensible-but-odd results on some rows — `aloo_dum` over
    `dum_aloo` for instance — and 341 of those is not a decision to make by
    convention.
  * **24 of the groups are not duplicates at all.** They disagree about
    `course_type` or `primary_protein`, which means one of the two rows is
    MISFILED and merging would bury the evidence. `chilli_baby_corn` is a
    `veg_dry` beside `baby_corn_chilli` as a `veg_gravy`; `butter_garlic_
    vegetables` is filed `healthy_rice` beside `garlic_butter_vegetables` as a
    `veg_dry`; `dal_rajma` carries `toor_dal` beside `rajma_dal` carrying
    `kidney_bean`. Those need a verdict, not a fold.

Current counts: **313 duplicate groups (341 rows would go) and 24 misfiles**
across the five cities.

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
}

# Words that name the FORM of a dish, kept apart from the core so a dry and a
# gravy of the same ingredients never group together. This is the distinction
# the whole audit turns on: `pepper_chicken_dry` and `pepper_chicken_gravy` are
# two dishes, not one written twice.
FORM_WORDS = frozenset({
    'dry', 'fry', 'roast', 'sukka', 'gravy', 'curry', 'masala', 'semi',
    'biryani', 'pulao', 'rice', 'tikka', 'kebab', 'kabab', 'soup', 'salad',
})


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
    for phrase, canon in PHRASES.items():
        text = text.replace(phrase, canon)
    tokens = [SYNONYMS.get(t, t) for t in text.split('_') if t]
    core = sorted(t for t in tokens if t not in FORM_WORDS)
    form = sorted(t for t in tokens if t in FORM_WORDS)
    return '|'.join(core), '|'.join(form)


def propose(names: list[str]) -> str:
    """The canonical name to suggest, chosen by a stated rule so it is stable.

    Prefer a name that spells its protein the English way (the word every other
    row and every menu reader uses), then the longest — a longer name carries
    more of the dish — then alphabetically, purely so two runs agree.
    """
    def rank(n: str) -> tuple:
        english = any(w in n.split('_') for w in
                      ('chicken', 'egg', 'mutton', 'fish', 'prawn'))
        return (not english, -len(n), n)
    return sorted(names, key=rank)[0]


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
