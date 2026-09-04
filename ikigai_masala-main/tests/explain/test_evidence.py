"""Evidence pack construction, and the validator that makes the prose safe.

The validator tests are the important ones. They are the difference between an
explanation layer and a fluent-nonsense generator pointed at a client.
"""

import json

import pytest

from src.explain.evidence import (
    attach_relaxations, attrs_from_dataframe, build_dishes, build_evidence,
    build_plan_evidence, build_provenance,
)
from src.explain.renderer import day_summary, render_day, render_plan

ATTRS = {
    'veg_kurma':   {'item_color': 'green', 'texture': 'saucy', 'spice_level': 2,
                    'richness_score': 4, 'key_ingredient': 'mixed_veg',
                    'primary_protein': 'coconut', 'cuisine_family': 'south_indian',
                    'course_type': 'veg_gravy'},
    'jowar_roti':  {'item_color': 'brown', 'texture': 'bready', 'spice_level': 0,
                    'richness_score': 1, 'key_ingredient': 'jowar',
                    'primary_protein': 'jowar', 'cuisine_family': 'south_indian',
                    'course_type': 'bread'},
    'curd':        {'item_color': 'white', 'texture': 'soft', 'spice_level': 0,
                    'richness_score': 1, 'key_ingredient': 'curd',
                    'primary_protein': 'yogurt', 'cuisine_family': 'south_indian',
                    'course_type': 'curd_side'},
}

DAY_ITEMS = {'veg_gravy': 'veg_kurma', 'bread': 'jowar_roti', 'curd_side': 'curd'}


class TestBuildDishes:
    def test_accepts_bare_strings(self):
        d = build_dishes(DAY_ITEMS, ATTRS)
        assert d['bread']['name'] == 'jowar_roti'
        assert d['bread']['texture'] == 'bready'

    def test_accepts_the_plan_response_shape(self):
        """`/plan` returns {'item_base': ..., 'is_nonveg': ...} per slot."""
        shaped = {'bread': {'item_base': 'jowar_roti', 'is_nonveg': False}}
        assert build_dishes(shaped, ATTRS)['bread']['name'] == 'jowar_roti'

    def test_unknown_dish_is_kept_not_dropped(self):
        """A dish we cannot describe is exactly the one worth showing a human.

        Dropping it would make the plate look better than it is — the same
        silent-success failure mode the ontology audits exist to catch.
        """
        d = build_dishes({'rice': 'chuteny'}, ATTRS)
        assert d['rice']['name'] == 'chuteny'
        assert d['rice']['texture'] is None

    @pytest.mark.parametrize('junk', ['nan', 'NaN', '', '   ', 'None'])
    def test_blank_markers_become_none(self, junk):
        attrs = {'x': {'texture': junk, 'item_color': 'red'}}
        assert build_dishes({'rice': 'x'}, attrs)['rice']['texture'] is None

    def test_numpy_scalars_survive_json(self):
        np = pytest.importorskip('numpy')
        attrs = {'x': {'spice_level': np.int64(2), 'richness_score': np.float64(3.5)}}
        json.dumps(build_dishes({'rice': 'x'}, attrs))


class TestProvenance:
    def test_pinned_beats_freshness(self):
        """A pinned dish is on the plate because it is pinned, full stop."""
        dishes = build_dishes(DAY_ITEMS, ATTRS)
        p = build_provenance(dishes, recency={'curd': 99},
                             constant_items={'curd_side': 'curd'})
        curd = [x for x in p if x['dish'] == 'curd']
        assert curd and curd[0]['reason'] == 'client_constant'

    def test_freshness_only_past_the_threshold(self):
        dishes = build_dishes(DAY_ITEMS, ATTRS)
        near = build_provenance(dishes, recency={'veg_kurma': 3})
        far = build_provenance(dishes, recency={'veg_kurma': 26})
        assert not [x for x in near if x['reason'] == 'freshness']
        assert '26 days' in [x for x in far if x['dish'] == 'veg_kurma'][0]['detail']

    def test_rule_comment_is_used_verbatim(self):
        """`docs/client_rules_index.md` already renders the client's own
        sentence from `_comment`. Reuse it rather than inventing phrasing."""
        dishes = build_dishes(DAY_ITEMS, ATTRS)
        note = 'client asks for a millet bread on south days'
        p = build_provenance(dishes, rule_notes={'bread': note})
        assert [x for x in p if x['dish'] == 'jowar_roti'][0]['detail'] == note


class TestEvidencePack:
    def test_shape_and_serialisability(self):
        pack = build_evidence(date='2026-09-10', day_items=DAY_ITEMS, attrs=ATTRS,
                              theme='south', client_name='C', city='Bangalore')
        assert pack['weekday'] == 'Thursday'
        assert len(pack['checks']) == 6
        json.dumps(pack)

    def test_non_working_days_are_skipped(self):
        sol = {
            '2026-09-10': {'day_type': 'south', 'is_working_day': True,
                           'items': {'bread': {'item_base': 'jowar_roti'}}},
            '2026-09-11': {'is_working_day': False, 'items': {}},
        }
        packs = build_plan_evidence(solution=sol, attrs=ATTRS)
        assert [p['date'] for p in packs] == ['2026-09-10']

    def test_relaxations_attach_to_every_day(self):
        packs = [build_evidence(date='2026-09-10', day_items=DAY_ITEMS, attrs=ATTRS)]
        attach_relaxations(packs, [{'rule': 'liquid_desserts_twice',
                                    'detail': 'min 2 capped to 1'}])
        assert packs[0]['relaxations'][0]['rule'] == 'liquid_desserts_twice'

    def test_attrs_from_dataframe(self):
        pd = pytest.importorskip('pandas')
        df = pd.DataFrame([{'item': 'veg_kurma', 'texture': 'saucy',
                            'item_color': 'green'}])
        a = attrs_from_dataframe(df)
        assert a['veg_kurma']['texture'] == 'saucy'


class TestRenderer:
    def test_bullets_render_without_any_llm(self):
        pack = build_evidence(date='2026-09-10', day_items=DAY_ITEMS,
                              attrs=ATTRS, theme='south')
        lines = render_day(pack)
        assert any('Thursday' in l for l in lines)
        assert render_plan([pack])

    def test_failures_are_always_shown(self):
        """A summary that only reports good news teaches people to ignore it."""
        pack = build_evidence(date='2026-09-10', day_items=DAY_ITEMS, attrs=ATTRS)
        out = '\n'.join(render_day(pack, show_passing=False))
        assert '[!]' in out

    def test_summary_leads_with_failures(self):
        pack = build_evidence(date='2026-09-10', day_items=DAY_ITEMS, attrs=ATTRS)
        assert 'check:' in day_summary(pack)


# --------------------------------------------------------------------------
# The validator. This is what stops the feature inventing rationale.
# --------------------------------------------------------------------------

@pytest.fixture
def pack():
    return build_evidence(date='2026-09-10', day_items=DAY_ITEMS, attrs=ATTRS,
                          theme='south')


class TestValidator:
    @staticmethod
    def _v(prose, pack):
        from api.explain_llm import validate
        return validate(prose, pack)

    def test_grounded_prose_is_accepted(self, pack):
        ok, why = self._v('Thursday leans south with jowar_roti alongside '
                          'veg_kurma. The plate carries 2 textures.', pack)
        assert ok, why

    def test_a_true_but_unsourced_number_is_still_rejected(self, pack):
        """'3 textures' is arithmetically defensible if you count the curd,
        but the pack scopes textures to MAIN courses and reports 2. The
        validator has no opinion on truth — only on provenance. Anything the
        pack did not say, the prose may not say."""
        assert not self._v('The plate carries 3 textures.', pack)[0]

    def test_invented_number_is_rejected(self, pack):
        """The core guarantee: a plausible statistic that came from nowhere."""
        ok, why = self._v('This plate scores 87 percent on balance.', pack)
        assert not ok and '87' in why

    def test_invented_dish_is_rejected(self, pack):
        ok, why = self._v('Served with fresh paneer_tikka on the side.', pack)
        assert not ok and 'paneer_tikka' in why

    @pytest.mark.parametrize('bad', [
        'A healthy plate with balanced nutrition.',
        'Around 600 calories per serving.',
        'Good for diabetic staff members.',
        'Rich in vitamin content.',
    ])
    def test_health_claims_are_rejected(self, bad, pack):
        """Liability boundary, not a style preference. You are a caterer."""
        assert not self._v(bad, pack)[0]

    def test_empty_reply_is_rejected(self, pack):
        assert not self._v('   ', pack)[0]

    def test_rejection_falls_back_to_bullets_not_a_patched_sentence(self, pack, monkeypatch):
        """A half-trusted sentence is worse than a bullet list — nobody can
        tell which half to trust. Rejected replies are discarded whole."""
        import api.explain_llm as mod
        mod.reset_cache_for_tests()
        monkeypatch.setattr(mod, 'ENABLED', True)
        monkeypatch.setattr(mod, '_call_model', lambda payload: json.dumps(
            {'days': [{'date': '2026-09-10',
                       'prose': 'A perfectly balanced 99 point plate.'}]}))
        out = mod.explain_plan([pack])['2026-09-10']
        assert out['prose'] is None
        assert out['llm_used'] is False
        assert out['bullets']
        assert 'rejected' in out['reason']

    def test_bad_reply_is_never_cached(self, pack, monkeypatch):
        import api.explain_llm as mod
        mod.reset_cache_for_tests()
        monkeypatch.setattr(mod, 'ENABLED', True)
        monkeypatch.setattr(mod, '_call_model', lambda payload: json.dumps(
            {'days': [{'date': '2026-09-10', 'prose': 'Scores 42 overall.'}]}))
        mod.explain_plan([pack])
        assert mod._cache == {}

    def test_model_unavailable_still_returns_bullets(self, pack, monkeypatch):
        import api.explain_llm as mod
        mod.reset_cache_for_tests()
        monkeypatch.setattr(mod, 'ENABLED', True)
        monkeypatch.setattr(mod, '_call_model', lambda payload: None)
        out = mod.explain_plan([pack])['2026-09-10']
        assert out['prose'] is None and out['bullets']

    def test_disabled_is_the_default_path(self, pack):
        import api.explain_llm as mod
        mod.reset_cache_for_tests()
        out = mod.explain_plan([pack])['2026-09-10']
        assert out['llm_used'] is False and out['bullets']
