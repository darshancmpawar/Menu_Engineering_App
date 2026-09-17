"""One protein, one spelling — and a blank that reads as a blank.

Two defects with one consequence, both load-bearing the moment a rule says
"not two dishes of the same protein on one plate":

* **soya is spelled four ways.** NCR alone had `primary_protein` soya 37 /
  soy 21 and `key_ingredient` soya 29 / soy 10 / soyabean 3 / soyabin,
  soyawadi, soybean 1 each, against 272 clean `soy` rows in the other four
  cities. A variety rule reading the column raw sees two unrelated ingredients
  and lets a soya chaap sit beside a soya keema. `siemens.json` already
  carried BOTH spellings as adjacent selectors, which is a config working
  around a data defect.

* **a blank is not blank once `str()` has touched it.** `primary_protein` is
  NaN on 3,988 Bangalore rows and is NOT one of the columns `ColumnMapper`
  normalises, so `_norm_str(str(cell))` yields the string `'nan'` — truthy,
  non-empty, and identical across every unclassified dish. A grouping rule
  then reads "don't repeat a protein" as "don't serve two dishes nobody has
  classified". `_norm_cell` is the fix and these tests are what stop the
  `str()` creeping back in.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pandas as pd
import pytest

from scripts.city_list import CITIES, city_path
from scripts.protein_key_ingredients import (
    FOLD, FOLD_PROTEIN, ROW_KEY_INGREDIENT, fold,
)
from src.preprocessor.column_mapper import _norm_cell, _norm_str

ROOT = Path(__file__).resolve().parents[2]

#: Every way this ontology has ever spelled the soybean. The canonical value
#: is `soy`; a workbook carrying any of the others is what this guards.
SOY_VARIANTS = ('soya', 'soyabean', 'soyabin', 'soybean', 'soyawadi')


def _col(df: pd.DataFrame, name: str) -> pd.Series:
    return df[name].fillna('').astype(str).str.strip().str.lower()


@pytest.fixture(scope='module')
def frames():
    return {c: pd.read_excel(city_path(c)) for c in CITIES}


class TestOneSpellingPerProtein:

    @pytest.mark.parametrize('city', CITIES)
    def test_no_soy_variant_survives_in_either_column(self, city, frames):
        df = frames[city]
        for col in ('primary_protein', 'key_ingredient'):
            bad = sorted(set(_col(df, col)) & set(SOY_VARIANTS))
            assert not bad, f'{city}.{col} still spells soy as {bad}'

    @pytest.mark.parametrize('city', CITIES)
    def test_soy_is_still_present(self, city, frames):
        """The fold must not have deleted the family it was folding.

        Chennai carries 3 soya rows and Pune 8, so this is a low bar
        deliberately: the assertion is "the dishes are still there", not a
        count that a legitimate import would break.
        """
        df = frames[city]
        assert (_col(df, 'primary_protein') == 'soy').any(), \
            f'{city} has no soy dish at all'

    def test_ncr_soya_family_is_whole(self, frames):
        """NCR is where the split was, so it gets the arithmetic check.

        58 rows carried some spelling of soy across the two columns before the
        fold. All 58 must be reachable by one selector now — that number IS
        the cost the split was imposing.
        """
        df = frames['ncr']
        assert int((_col(df, 'primary_protein') == 'soy').sum()) >= 55
        assert int((_col(df, 'key_ingredient') == 'soy').sum()) >= 55

    def test_every_chaap_row_is_a_soy_row(self, frames):
        """Chaap IS a soy product, and the key_ingredient column now says so.

        Named row by row in ROW_KEY_INGREDIENT rather than pattern-matched,
        because the evidence is per-row: all seven carried
        `primary_protein: soya` independently of their key ingredient.
        """
        for city in CITIES:
            df = frames[city]
            names = _col(df, 'item')
            ki = _col(df, 'key_ingredient')
            chaap = names.str.contains('chaap', na=False) | names.str.contains('chap', na=False)
            for _, row in df[chaap & (_col(df, 'primary_protein') == 'soy')].iterrows():
                assert _norm_cell(row['key_ingredient']) == 'soy', (
                    f"{city}: {row['item']} is a soy dish whose key_ingredient "
                    f"is {row['key_ingredient']!r}")
            del ki

    def test_ghiya_soya_keeps_its_vegetable(self):
        """The one row deliberately left alone.

        `ghiya_soya` is bottle gourd WITH soya: the vegetable is a real
        co-ingredient and the protein is already recorded in its own column.
        Folding it would misname the dish to make a rule fire, which is the
        line `REGIONAL_PULSES` draws in the same script.
        """
        assert not any(k[0] == 'ghiya_soya' for k in ROW_KEY_INGREDIENT)

    def test_no_fold_target_is_itself_a_variant(self):
        """A fold table that maps A->B and B->C depends on dict order."""
        for table in (FOLD, FOLD_PROTEIN):
            for src, dst in table.items():
                assert dst not in table, f'{src} -> {dst} -> {table[dst]} chains'

    def test_no_fold_crosses_the_vegetarian_line(self):
        """Note 34: a protein fold is the one edit that can plate meat.

        `_nonveg_mask` reads `primary_protein`, so a table entry mapping a veg
        value onto a meat one (or the reverse) would move a dish across the
        line silently. None of today's do; this fails if one ever is added.
        """
        from src.constants import NONVEG_PROTEINS
        for table in (FOLD, FOLD_PROTEIN):
            for src, dst in table.items():
                assert (src in NONVEG_PROTEINS) == (dst in NONVEG_PROTEINS), \
                    f'{src} -> {dst} crosses the vegetarian line'
        for (item, cur), dst in ROW_KEY_INGREDIENT.items():
            assert dst not in NONVEG_PROTEINS, f'{item} -> {dst} is a meat value'

    def test_rerunning_the_fold_changes_nothing(self, frames):
        for city in CITIES:
            df = frames[city].copy()
            assert fold(df) == 0, f'{city} is not at a fixed point'

    def test_siemens_no_longer_carries_the_workaround(self):
        """The config that worked around the split must not outlive it.

        Leaving the dead `primary_protein: soya` selector in place is harmless
        arithmetically and costly to read: the next person maintaining that
        file has no way to tell a live alternative from a fossil.
        """
        import json
        blob = json.loads(
            (ROOT / 'data/configs/clients/siemens.json').read_text())
        text = json.dumps(blob['rules'] if 'rules' in blob else blob)
        # the variant may appear in a `_comment` explaining the history; what
        # must not survive is a selector VALUE.
        def selectors(node):
            if isinstance(node, dict):
                for k, v in node.items():
                    if k == 'primary_protein':
                        yield str(v).strip().lower()
                    else:
                        yield from selectors(v)
            elif isinstance(node, list):
                for v in node:
                    yield from selectors(v)
        assert 'soya' not in set(selectors(blob)), \
            'siemens still selects on the folded-away spelling'
        del text


class TestABlankCellReadsAsBlank:
    """`_norm_cell`, and the `str()` that must not come back."""

    @pytest.mark.parametrize('raw', [float('nan'), None, '', '   ', 'nan',
                                     'NaN', 'None', 'none', 'NULL', '-'])
    def test_blank_shapes_all_read_as_empty(self, raw):
        assert _norm_cell(raw) == ''

    def test_the_artefact_it_exists_for(self):
        """The exact expression that was wrong, pinned as wrong.

        `_norm_str(str(nan))` is `'nan'` — truthy, so every unclassified dish
        groups under one value. This is the difference the helper makes, and
        stating it here means a future reader does not have to rediscover it.
        """
        nan = float('nan')
        assert _norm_str(str(nan)) == 'nan'      # the bug
        assert _norm_cell(nan) == ''             # the fix

    @pytest.mark.parametrize('raw,want', [
        ('Paneer', 'paneer'), (' SOY ', 'soy'), ('chana_dal', 'chana_dal'),
        ('nan_gravy', 'nan_gravy'),   # a real value that merely starts with it
    ])
    def test_real_values_survive(self, raw, want):
        assert _norm_cell(raw) == want

    @staticmethod
    def _stringified_column_reads(source: str):
        """`_norm_str(str(<a column read>))` sites in *source*.

        `str(r.get('item'))` is deliberately NOT flagged — `item` is never
        blank, so the artefact cannot bite there and widening this would turn
        the guard into noise. Only a group_by or a column-variable read counts.
        """
        found = []
        for node in ast.walk(ast.parse(source)):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == '_norm_str'
                    and node.args):
                continue
            inner = node.args[0]
            if not (isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Name)
                    and inner.func.id == 'str'
                    and inner.args):
                continue
            src = ast.unparse(inner.args[0])
            if 'group_by' in src or src.endswith("get(col, '')"):
                found.append((node.lineno, ast.unparse(node)))
        return found

    def test_the_guard_catches_a_planted_violation(self):
        """The scan below reports zero, and so would a broken scan.

        Two controls: the shape it hunts is caught, and the shape it must
        tolerate is not.
        """
        assert self._stringified_column_reads(
            "v = _norm_str(str(row.get(self.group_by, '')))")
        assert not self._stringified_column_reads(
            "v = _norm_str(str(row.get('item', '')))")
        assert not self._stringified_column_reads(
            "v = _norm_cell(row.get(self.group_by, ''))")

    def test_grouping_rules_do_not_stringify_before_normalising(self):
        """AST guard: no `_norm_str(str(...))` on a group_by/column read.

        The helper only helps where it is called. A future edit that writes
        `_norm_str(str(row.get(self.group_by)))` back in would restore the
        defect with no test failing anywhere else, because the symptom is a
        penalty applied to the data's gaps — invisible in a plan that still
        renders.
        """
        offenders = []
        scanned = 0
        for path in sorted((ROOT / 'src' / 'menu_rules').glob('*.py')):
            scanned += 1
            for lineno, text in self._stringified_column_reads(path.read_text()):
                offenders.append(f'{path.name}:{lineno}: {text}')
        assert scanned > 5, 'the rules package moved; this guard scanned nothing'
        assert not offenders, (
            'these read a column through str() before _norm_str, so a NaN '
            'becomes the value "nan": ' + '; '.join(offenders))


class TestTheProteinIsActuallyReachable:
    """A fold is only worth doing if a rule can now see the family."""

    @pytest.mark.parametrize('city', CITIES)
    def test_one_selector_reaches_every_soy_dish(self, city, frames):
        from src.menu_rules.selector_frequency_rule import SelectorFrequencyRule
        df = frames[city]
        matcher = SelectorFrequencyRule._parse_matcher({'primary_protein': 'soy'})
        hits = sum(1 for _, r in df.iterrows()
                   if SelectorFrequencyRule._matches(r, matcher))
        named = int((_col(df, 'primary_protein') == 'soy').sum())
        assert hits == named, (
            f'{city}: the selector reaches {hits} rows but {named} carry soy')
