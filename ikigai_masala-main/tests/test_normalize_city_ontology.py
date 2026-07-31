"""The city-ontology normaliser (scripts/normalize_city_ontology.py).

It is the only sanctioned way a raw city workbook becomes
``data/raw/city_items/<city>.xlsx``, so the transformation it applies is worth
pinning: column set forced to the reference format, flags coerced to 0/1, and the
``client`` pool column set so a client with ``source_pools = []`` sees the list.
"""

import pandas as pd
import pytest

from scripts.normalize_city_ontology import _coerce_flag, normalize

REFERENCE = pd.DataFrame(columns=[
    'item_id', 'item', 'course_type', 'client', 'is_rice', 'is_dal',
])


def _src(**overrides):
    row = {
        'item_id': 'MENU000001', 'item': 'dal_fry', 'course_type': 'dal',
        'client': 'Amadeus Pune', 'is_rice': 0, 'is_dal': 1,
    }
    row.update(overrides)
    return pd.DataFrame([row])


class TestCoerceFlag:
    @pytest.mark.parametrize('value', [1, '1', 1.0, '1.0', 'yes', 'TRUE', 'Y'])
    def test_truthy(self, value):
        assert _coerce_flag(value) == 1

    @pytest.mark.parametrize('value', [0, '0', None, '', 'no', 'nan', float('nan')])
    def test_falsy(self, value):
        assert _coerce_flag(value) == 0

    def test_unrecognised_text_is_zero_not_one(self):
        """A stray note in a flag column must not read as 'set'."""
        assert _coerce_flag('check this') == 0


class TestNormalize:
    def test_columns_forced_to_the_reference_set_and_order(self):
        src = _src()
        src['stray_column'] = 'x'
        out, report = normalize(src, REFERENCE)
        assert list(out.columns) == list(REFERENCE.columns)
        assert report['extra_columns'] == ['stray_column']

    def test_missing_column_is_added_empty_and_reported(self):
        src = _src().drop(columns=['is_rice'])
        out, report = normalize(src, REFERENCE)
        assert 'is_rice' in out.columns
        assert report['missing_columns'] == ['is_rice']
        assert out['is_rice'].iloc[0] == 0  # flag columns coerce NA to 0

    def test_flags_are_integers(self):
        out, _report = normalize(_src(is_dal='yes', is_rice=None), REFERENCE)
        assert out['is_dal'].iloc[0] == 1
        assert out['is_rice'].iloc[0] == 0
        assert out['is_dal'].dtype.kind == 'i'

    def test_only_changed_flag_columns_are_reported(self):
        _out, report = normalize(_src(is_dal='yes'), REFERENCE)
        assert report['coerced_flag_columns'] == ['is_dal']

    def test_client_column_defaults_to_common(self):
        """A workbook tagging every row with one client name carries no per-client
        information, and a client with source_pools=[] would see nothing."""
        out, _report = normalize(_src(), REFERENCE)
        assert out['client'].iloc[0] == 'common'

    def test_client_keep_leaves_the_column_alone(self):
        out, _report = normalize(_src(), REFERENCE, client_pool='keep')
        assert out['client'].iloc[0] == 'Amadeus Pune'

    def test_text_is_trimmed(self):
        out, _report = normalize(_src(item='  dal_fry  '), REFERENCE)
        assert out['item'].iloc[0] == 'dal_fry'

    def test_duplicate_item_ids_are_reported(self):
        src = pd.concat([_src(), _src()], ignore_index=True)
        _out, report = normalize(src, REFERENCE)
        assert report['duplicate_item_ids'] == 1

    def test_row_count_is_preserved(self):
        src = pd.concat([_src(), _src(item_id='MENU000002', item='dal_tadka')],
                        ignore_index=True)
        out, report = normalize(src, REFERENCE)
        assert len(out) == 2 and report['rows'] == 2


class TestShippedPuneFileMatchesTheScript:
    def test_rerunning_the_normaliser_is_a_no_op(self):
        """The committed Pune workbook must be exactly what the script produces,
        so nobody has to wonder whether it was hand-edited afterwards."""
        from api.config import DEFAULT_EXCEL_PATH, city_excel_path
        pune = pd.read_excel(city_excel_path('Pune'))
        reference = pd.read_excel(DEFAULT_EXCEL_PATH)
        again, report = normalize(pune, reference)
        assert report['missing_columns'] == []
        assert report['extra_columns'] == []
        assert report['coerced_flag_columns'] == []
        assert report['duplicate_item_ids'] == 0
        assert list(again.columns) == list(pune.columns)
