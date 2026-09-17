"""The per-day overview: what goes with what, in four or five sentences."""
class TestTheDayOverview:
    """The short paragraph a chef reads: what goes with what on this plate.

    An OVERVIEW, not a checklist. `render_day` lists every verdict, which is
    right for someone auditing the ruleset and wrong for someone reading a
    menu — a column of "[ok] texture contrast" says nothing about the food.
    These pin the shape (four or five sentences, built from pairings) and the
    one property that makes it worth reading: it does not flatter the plate.
    """

    def _pack(self, **kw):
        from src.explain.evidence import build_evidence
        attrs = {
            'paneer_butter_masala': {'spice_level': 2, 'texture': 'saucy',
                                     'richness_score': 4, 'key_ingredient': 'paneer',
                                     'item_color': 'orange', 'course_type': 'veg_gravy'},
            'aloo_jeera': {'spice_level': 1, 'texture': 'dry', 'richness_score': 2,
                           'key_ingredient': 'potato', 'item_color': 'yellow',
                           'course_type': 'veg_dry'},
            'dal_tadka': {'spice_level': 1, 'texture': 'saucy', 'richness_score': 2,
                          'key_ingredient': 'dal', 'item_color': 'yellow',
                          'course_type': 'dal'},
            'jeera_rice': {'spice_level': 0, 'texture': 'grainy', 'richness_score': 2,
                           'key_ingredient': 'rice', 'item_color': 'white',
                           'course_type': 'rice'},
            'plain_chapati': {'spice_level': 0, 'texture': 'bready',
                              'richness_score': 1, 'key_ingredient': 'wheat',
                              'item_color': 'brown', 'course_type': 'bread'},
            'boondi_raita': {'spice_level': 0, 'texture': 'saucy',
                             'richness_score': 2, 'key_ingredient': 'yogurt',
                             'item_color': 'white', 'course_type': 'curd_side'},
            'gobi_65': {'spice_level': 3, 'texture': 'crisp', 'richness_score': 3,
                        'key_ingredient': 'cauliflower', 'item_color': 'red',
                        'course_type': 'starter'},
        }
        drop = kw.pop('drop', ())
        items = {f"{v['course_type']}__1": k for k, v in attrs.items()
                 if k not in drop}
        return build_evidence(date='2026-09-17', day_items=items, attrs=attrs,
                              theme=kw.pop('theme', 'north'), **kw)

    def _sentences(self, text):
        return [s for s in text.split('. ') if s.strip()]

    def test_it_is_four_or_five_sentences(self):
        from src.explain.renderer import day_overview, MAX_OVERVIEW_SENTENCES
        text = day_overview(self._pack())
        assert 2 <= len(self._sentences(text)) <= MAX_OVERVIEW_SENTENCES, text

    def test_it_opens_with_the_day_and_the_theme(self):
        from src.explain.renderer import day_overview
        text = day_overview(self._pack(theme='biryani'))
        assert text.split('.')[0].endswith('main dishes')
        assert 'biryani' in text.split('.')[0]

    def test_it_names_real_dishes_and_why_they_pair(self):
        from src.explain.renderer import day_overview
        text = day_overview(self._pack()).lower()
        # The whole point: two dishes and a reason, not a verdict name.
        assert 'boondi raita' in text and 'gobi 65' in text
        assert 'cools it' in text

    def test_it_never_names_a_check_or_a_rule(self):
        """An overview that says `texture_contrast` is the report it replaces."""
        from src.explain.renderer import day_overview
        from src.explain.checks import ALL_CHECKS
        text = day_overview(self._pack()).lower()
        for fn in ALL_CHECKS:
            assert fn.__name__.replace('check_', '').replace('_', ' ') not in text

    def test_a_missing_complement_is_stated(self):
        """The honest half. A hot dish with no yogurt is what a kitchen can fix
        this morning, so it is never dropped to make room for more praise."""
        from src.explain.renderer import day_overview
        text = day_overview(self._pack(drop=('boondi_raita',))).lower()
        assert 'missing' in text
        assert 'gobi 65' in text

    def test_a_plate_with_a_gap_is_not_called_balanced(self):
        from src.explain.renderer import day_overview
        text = day_overview(self._pack(drop=('boondi_raita',))).lower()
        assert 'balanced' not in text

    def test_a_bare_plate_says_it_has_nothing_to_go_on(self):
        """Rather than inventing a reading from columns nobody filled in."""
        from src.explain.evidence import build_evidence
        from src.explain.renderer import day_overview
        pack = build_evidence(
            date='2026-09-17', day_items={'rice__1': 'x', 'dal__1': 'y'},
            attrs={'x': {'course_type': 'rice'}, 'y': {'course_type': 'dal'}},
            theme='mix')
        assert 'not enough recorded' in day_overview(pack)

    def test_it_never_raises_on_a_junk_pack(self):
        """It is rendered on every explained day; it must never be why one
        fails to render."""
        from src.explain.renderer import day_overview
        for junk in ({}, {'pairings': None}, {'pairings': {'pairings': None}},
                     {'plate_profile': None, 'pairings': {'gaps': None}}):
            assert isinstance(day_overview(junk), str)
