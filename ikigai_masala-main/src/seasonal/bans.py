"""Seasonal high-risk vegetables: which list applies, and which dishes it hits.

Two inputs, both reviewed files under ``data/configs/seasonal_bans/``:

* ``<year>.json``: month -> region -> red / yellow / notes / salad_bans /
  alternatives, generated from the sheet by ``scripts/build_seasonal_bans.py``.
* ``vegetables.json``: for each vegetable, the workbook ``key_ingredient``
  values and dish-name patterns that identify a dish containing it.

Why both a key ingredient and the name. The workbooks carry one
``key_ingredient`` per dish, so ``aloo_gobi`` is "potato" and would slip
through on that field alone; its name says gobi. In October the name catches
about 80 Bangalore dishes the field misses. The patterns are deliberately
local (gobi, baingan, vankaya, bendakaya, dosakai...) and careful: "patta gobi"
is cabbage, not cauliflower.

What this cannot see: a "mixed vegetables" dish lists no contents, so it is
never matched. That is a product decision, not a gap: the kitchen leaves the
red-list vegetables out, and the planner's seasonal panel says so.

Pure and network-free, like the rest of ``src/``.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[2] / 'data' / 'configs' / 'seasonal_bans'


@dataclass(frozen=True)
class MonthBans:
    """One month's lists for one region."""
    year: int
    month: int
    region: str
    red: frozenset = field(default_factory=frozenset)
    yellow: frozenset = field(default_factory=frozenset)
    notes: tuple = ()
    salad_bans: frozenset = field(default_factory=frozenset)
    alternatives: tuple = ()

    @property
    def key(self) -> str:
        return f'{self.year}-{self.month:02d}'

    @property
    def label(self) -> str:
        return dt.date(self.year, self.month, 1).strftime('%B %Y')

    def is_empty(self) -> bool:
        return not (self.red or self.yellow or self.salad_bans)


@lru_cache(maxsize=4)
def _load_year(path: str) -> Dict[str, Any]:
    return json.loads(Path(path).read_text())


@lru_cache(maxsize=1)
def load_vocabulary() -> Dict[str, Any]:
    return json.loads((DATA_DIR / 'vegetables.json').read_text())


def _year_file(year: int) -> Optional[Path]:
    """The sheet for ``year``, or the latest one before it.

    A new year's sheet may arrive late; using last year's list for the same
    month is safer than banning nothing, and the panel shows which sheet it is.
    """
    files = sorted((int(p.stem), p) for p in DATA_DIR.glob('[0-9][0-9][0-9][0-9].json'))
    chosen = None
    for y, p in files:
        if y <= year:
            chosen = p
    return chosen or (files[0][1] if files else None)


def region_for_city(city: Optional[str], year: Optional[int] = None) -> Optional[str]:
    path = _year_file(year or dt.date.today().year)
    if not path or not city:
        return None
    mapping = _load_year(str(path)).get('region_for_city', {})
    for c, region in mapping.items():
        if c.strip().lower() == str(city).strip().lower():
            return region
    return None


def bans_for(city: Optional[str], date: dt.date) -> Optional[MonthBans]:
    """The lists that apply to ``city`` on ``date``, or None if there are none."""
    path = _year_file(date.year)
    region = region_for_city(city, date.year)
    if not path or not region:
        return None
    data = _load_year(str(path))
    entry = (data.get('months', {}).get(f'{date.month:02d}') or {}).get(region)
    if not entry:
        return None
    return MonthBans(
        year=date.year, month=date.month, region=region,
        red=frozenset(entry.get('red', [])), yellow=frozenset(entry.get('yellow', [])),
        notes=tuple(entry.get('notes', [])), salad_bans=frozenset(entry.get('salad_bans', [])),
        alternatives=tuple(entry.get('alternatives', [])),
    )


def bans_by_month(city: Optional[str], dates: Iterable[dt.date]) -> List[MonthBans]:
    """Distinct month lists covering ``dates``, in date order."""
    out: Dict[str, MonthBans] = {}
    for d in sorted(set(dates)):
        b = bans_for(city, d)
        if b is not None and b.key not in out:
            out[b.key] = b
    return list(out.values())


def vegetable_label(canonical: str) -> str:
    spec = load_vocabulary()['vegetables'].get(canonical) or {}
    return spec.get('label') or canonical.capitalize()


class VegetableMatcher:
    """Which dishes contain which vegetables, by key ingredient or name."""

    def __init__(self, vocabulary: Optional[Dict[str, Any]] = None):
        vocab = vocabulary or load_vocabulary()
        self._ki: Dict[str, Set[str]] = {}
        self._patterns: Dict[str, re.Pattern] = {}
        for canon, spec in vocab['vegetables'].items():
            self._ki[canon] = {k.lower() for k in spec.get('key_ingredients', [])}
            pats = spec.get('name_patterns', [])
            if pats:
                self._patterns[canon] = re.compile('|'.join(f'(?:{p})' for p in pats))
        self._leafy_flag = vocab.get('leafy_flag_column')
        self._leafy_group = vocab.get('leafy_group')

    @staticmethod
    def _names(frame: pd.DataFrame) -> pd.Series:
        return frame['item'].astype(str).str.lower().str.replace('_', ' ', regex=False)

    def mask(self, frame: pd.DataFrame, vegetables: Iterable[str]) -> pd.Series:
        """Boolean Series: the row contains any of ``vegetables``."""
        vegetables = [v for v in vegetables if v]
        out = pd.Series(False, index=frame.index)
        if frame.empty or not vegetables:
            return out
        names = self._names(frame)
        ki = (frame['key_ingredient'].astype(str).str.strip().str.lower()
              if 'key_ingredient' in frame.columns else pd.Series('', index=frame.index))
        for v in vegetables:
            if self._ki.get(v):
                out |= ki.isin(self._ki[v])
            pat = self._patterns.get(v)
            if pat is not None:
                out |= names.str.contains(pat, regex=True)
            if v == self._leafy_group and self._leafy_flag in frame.columns:
                out |= pd.to_numeric(frame[self._leafy_flag], errors='coerce').fillna(0).eq(1)
        return out

    def vegetables_in(self, name: str, key_ingredient: Optional[str] = None,
                      candidates: Optional[Iterable[str]] = None,
                      leafy_flag: Any = None) -> Set[str]:
        """The vegetables (from ``candidates``, default all) one dish contains."""
        low = str(name or '').lower().replace('_', ' ')
        ki = str(key_ingredient or '').strip().lower()
        found = set()
        for v in (candidates if candidates is not None else self._ki.keys()):
            if ki and ki in self._ki.get(v, ()):
                found.add(v)
            elif self._patterns.get(v) is not None and self._patterns[v].search(low):
                found.add(v)
            elif v == self._leafy_group and str(leafy_flag) in ('1', '1.0', 'True'):
                found.add(v)
        return found

    def counts(self, frame: pd.DataFrame, vegetables: Sequence[str]) -> Dict[str, int]:
        """{vegetable: dishes containing it}, for the planner panel."""
        return {v: int(self.mask(frame, [v]).sum()) for v in vegetables}


@lru_cache(maxsize=1)
def default_matcher() -> VegetableMatcher:
    return VegetableMatcher()
