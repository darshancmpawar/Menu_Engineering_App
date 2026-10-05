"""Build data/configs/seasonal_bans/<year>.json from the high-risk vegetables sheet.

    python scripts/build_seasonal_bans.py path/to/High_risk_vegetables_2026.xlsx --year 2026

The sheet is free text written by people: typos (Bindi, Brijal, Bitter guard),
groups ("Green leafy vegetables"), a vegetable in both red and yellow, and
instructions mixed into the lists ("Note: Use tomato purée..."). This script is
the one place that reads it. It writes a clean, reviewable file and prints every
fragment it could not recognise, so a new year's sheet is checked by a person
before any menu uses it. The menu code only ever reads the JSON.

Rules it applies:
  * Red wins: a vegetable in both lists is red only.
  * Notes are kept word for word (deduplicated) for the kitchen.
  * "Do not use tomatoes in the salad" becomes ``salad_bans: ["tomato"]``.
  * Alternatives are kept as labels, minus anything red or yellow that month.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

ROOT = Path(__file__).resolve().parent.parent
VOCAB_PATH = ROOT / 'data' / 'configs' / 'seasonal_bans' / 'vegetables.json'
MONTHS = ['january', 'february', 'march', 'april', 'may', 'june', 'july',
          'august', 'september', 'october', 'november', 'december']
# Words left over after every vegetable is removed that carry no meaning.
_FILLER = {'and', 'all', 'its', 'stem', 'fresh', 'frozen', 'leaves', 'gourds', 'use', 'puree',
           'purée', 'vegetables', 'vegetable', 'fruits', 'fruit', 'only', 'the', 'of', 'to', 'in'}


def _spellings(vocab: dict) -> List[Tuple[str, List[str]]]:
    """(spelling, [canonical...]) longest first, so "tomato small" wins over "tomato"."""
    pairs: List[Tuple[str, List[str]]] = []
    for canon, spec in vocab['vegetables'].items():
        for s in spec['sheet']:
            pairs.append((s.lower(), [canon]))
    for s, canons in vocab.get('multi', {}).items():
        pairs.append((s.lower(), list(canons)))
    return sorted(pairs, key=lambda p: -len(p[0]))


def split_notes(cell: str) -> Tuple[str, List[str]]:
    """Cell text -> (list part, [note sentences])."""
    text = str(cell or '').replace('\u00a0', ' ')
    parts = re.split(r'note\s*:', text, flags=re.IGNORECASE)
    notes: List[str] = []
    for p in parts[1:]:
        for sent in re.split(r'(?<=[.!])\s+', p.strip()):
            sent = re.sub(r'\s+', ' ', sent).strip(' .')
            if sent:
                notes.append(sent + '.')
    return parts[0], notes


def parse_list(text: str, spellings) -> Tuple[Set[str], List[str]]:
    """List text -> (canonical vegetables, unrecognised fragments)."""
    low = ' ' + re.sub(r'(vegetables|fruits?)\s*:', ' ', str(text).lower()) + ' '
    found: Set[str] = set()
    for spelling, canons in spellings:
        pat = r'(?<![a-z])' + re.escape(spelling) + r'(?![a-z])'
        if re.search(pat, low):
            found.update(canons)
            low = re.sub(pat, ' ', low)
    leftover = [w for w in re.split(r'[^a-zé]+', low) if w and w not in _FILLER and len(w) > 1]
    return found, leftover


def alternatives(cell: str) -> List[str]:
    """'Arbi (Colocasia), Lauki (bottle gourd), ...' -> ['Arbi (Colocasia)', 'Lauki (bottle gourd)', ...]."""
    items, depth, cur = [], 0, ''
    for ch in str(cell or ''):
        depth += ch == '('
        depth -= ch == ')'
        if ch == ',' and depth == 0:
            items.append(cur)
            cur = ''
        else:
            cur += ch
    items.append(cur)
    return [re.sub(r'\s+', ' ', i).strip() for i in items if i.strip()]


def build(xlsx: Path, year: int) -> Tuple[dict, List[str]]:
    import pandas as pd
    vocab = json.loads(VOCAB_PATH.read_text())
    spellings = _spellings(vocab)
    df = pd.read_excel(xlsx)
    df.columns = ['month', 'region', 'red', 'yellow', 'alt'][:len(df.columns)]
    df['month'] = df['month'].ffill()
    months: Dict[str, Dict[str, dict]] = {}
    review: List[str] = []
    for _, r in df.iterrows():
        month_name = str(r['month']).strip().lower()
        if month_name not in MONTHS:
            review.append(f'unknown month {r["month"]!r}')
            continue
        key = f'{MONTHS.index(month_name) + 1:02d}'
        region = re.sub(r'\s+', ' ', str(r['region'])).strip()
        red_text, red_notes = split_notes(r['red'])
        yel_text, yel_notes = split_notes(r['yellow'])
        red, red_left = parse_list(red_text, spellings)
        yel, yel_left = parse_list(yel_text, spellings)
        overlap = red & yel
        yel -= red
        notes: List[str] = []
        for n in red_notes + yel_notes:
            if n.lower() not in {x.lower() for x in notes}:
                notes.append(n)
        salad_bans = (['tomato'] if any(re.search(r"(do not|don't).*tomato.*salad", n, re.I) for n in notes)
                      else [])
        alts = []
        for a in alternatives(r['alt']):
            got, _ = parse_list(a, spellings)
            if got & (red | yel):
                continue
            alts.append(a)
        months.setdefault(key, {})[region] = {
            'red': sorted(red), 'yellow': sorted(yel), 'notes': notes,
            'salad_bans': salad_bans, 'alternatives': alts,
            'raw': {'red': str(r['red']).strip(), 'yellow': str(r['yellow']).strip()},
        }
        where = f'{month_name.title()} / {region}'
        for w in red_left:
            review.append(f'{where}: red list fragment not recognised: {w!r}')
        for w in yel_left:
            review.append(f'{where}: yellow list fragment not recognised: {w!r}')
        for v in sorted(overlap):
            review.append(f'{where}: {v} is in both lists; kept as red')
    out = {
        '_comment': ('Generated by scripts/build_seasonal_bans.py from the high-risk vegetables sheet. '
                     'Review the printed report before committing; do not hand-edit, re-run the script.'),
        'year': year,
        'source': xlsx.name,
        'region_for_city': {'Bangalore': 'Karnataka', 'Hyderabad': 'AP & Telangana',
                            'Chennai': 'Tamilnadu', 'Pune': 'Maharashtra', 'NCR': 'North'},
        'months': dict(sorted(months.items())),
    }
    return out, review


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('xlsx', type=Path)
    ap.add_argument('--year', type=int, required=True)
    ap.add_argument('--out', type=Path, default=None)
    args = ap.parse_args(argv)
    data, review = build(args.xlsx, args.year)
    out = args.out or ROOT / 'data' / 'configs' / 'seasonal_bans' / f'{args.year}.json'
    out.write_text(json.dumps(data, indent=1, ensure_ascii=False) + '\n')
    regions = {r for m in data['months'].values() for r in m}
    try:
        shown = out.resolve().relative_to(ROOT)
    except ValueError:      # --out outside the repo
        shown = out
    print(f'wrote {shown}: {len(data["months"])} months x {len(regions)} regions')
    print(f'{len(review)} item(s) to review:' if review else 'nothing to review')
    for line in review:
        print('  -', line)
    return 0


if __name__ == '__main__':
    sys.exit(main())
