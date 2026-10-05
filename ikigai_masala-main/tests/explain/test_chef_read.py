"""The chef's read: draft -> check -> send problems back -> repeat.

Offline: `_post_model` is replaced, so no network is touched. The menu is the
real Eli Lilly Monday lunch (north day, 7 Sep 2026) from a test run, which is
also the worked example in docs/chef_read_architecture.md.
"""
import json

import pytest

import api.explain_llm as mod

DATE = '2026-09-07'


def _dish(name, course, cuisine, texture, spice, rich, key, kind, protein=None):
    return {'name': name, 'course_type': course, 'cuisine_family': cuisine, 'texture': texture,
            'spice_level': spice, 'richness_score': rich, 'key_ingredient': key,
            'primary_protein': protein, 'sub_category': kind}


@pytest.fixture
def pack():
    return {
        'date': DATE, 'weekday': 'Monday', 'theme': 'north',
        'dishes': {
            'salad': _dish('babycorn_and_sweet_pepper_salad', 'salad', 'continental', 'fresh', 0, 1, 'baby_corn', 'fresh_veg_salad'),
            'bread': _dish('jeera_chapati', 'bread', 'north_indian', 'bready', 0, 2, 'jeera', 'spice_chapatti'),
            'rice': _dish('mint_pulao', 'rice', 'north_indian', 'grainy', 0, 2, 'rice', 'north_simple_veg_pulao'),
            'white_rice': _dish('steamed rice', 'white_rice', 'south_indian', 'soft', 0, 1, 'rice', 'white_rice'),
            'veg_dry': _dish('soya_chatpata_dry', 'veg_dry', 'north_indian', 'dry', 1, 2, 'soy', 'chole_and_soya_dry', 'soy'),
            'veg_gravy': _dish('drumstick_mango_pachadi', 'veg_gravy', 'north_indian', 'saucy', 1, 2, 'drumstick', 'mixed_veg_curry'),
            'dal': _dish('pumpkin_kootu', 'dal', 'south_indian', 'saucy', 1, 2, 'pumpkin', 'kootu'),
            'sambar': _dish('dosakai_sambar', 'sambar', 'south_indian', 'saucy', 1, 2, 'dal', 'vegetable_sambar'),
            'rasam': _dish('rasam', 'rasam', 'south_indian', 'saucy', 1, 1, 'garlic', 'rasam'),
            'dessert': _dish('ghee_motichur_laddu', 'dessert', 'north_indian', 'soft', 0, 5, 'ghee', 'laddu'),
            'curd_side': _dish('plain_curd_and_raita', 'curd_side', 'north_indian', 'fresh', 0, 1, 'curd', 'raita'),
            'nonveg_main': _dish('chicken_pepper_fry', 'nonveg_main', 'north_indian', 'crisp', 2, 5, 'chicken', 'chicken_spicy_fry', 'chicken'),
        },
        'provenance': [{'dish': 'jeera_chapati', 'slot': 'bread', 'reason': 'theme', 'detail': 'matches the north theme'}],
        'pairings': {'pairings': [], 'gaps': []},
        'checks': [{'name': 'texture_contrast', 'passed': True, 'detail': '5 textures across 6 dishes'}],
        'relaxations': [],
    }


EXTRAS = {
    'soya_chatpata_dry': {'state_origin': 'Pan-North India', 'premium': True},
    'drumstick_mango_pachadi': {'state_origin': 'Pan-North India', 'premium': False},
    'pumpkin_kootu': {'state_origin': 'Tamil Nadu', 'premium': False},
    'chicken_pepper_fry': {'state_origin': 'Pan-North India', 'premium': False},
}
CITY = ['dal_makhani', 'chapati', 'jeera_chapati', 'soya_chatpata_dry', 'motichur_laddu',
        'ghee_motichur_laddu', 'paneer_butter_masala', 'pumpkin_kootu', 'mint_pulao']

GOOD = {
    'client_read': 'Two good ways to eat today. Roti people, pair the jeera chapati with the soya chatpata, '
                   'the pick of the day. Rice people, steamed rice with dosakai sambar, rasam and the pumpkin '
                   'kootu makes a proper South-style meal, with curd to round it off.',
    'internal_read': 'Says north on paper, but a north diner has nothing wet for the roti: the dal is a kootu and '
                     'the gravy a pachadi, both south. The south plate is the complete one. Heavy finish with '
                     'pepper fry then ghee laddu. The pachadi looks wrongly marked north.',
    'claims': {
        'plates': [{'for': 'north veg', 'dishes': ['jeera_chapati', 'soya_chatpata_dry']},
                   {'for': 'south veg', 'dishes': ['steamed rice', 'dosakai_sambar', 'rasam', 'pumpkin_kootu']}],
        'star': {'dish': 'soya_chatpata_dry', 'basis': 'premium', 'why': 'the premium veg dish most diners will take'},
        'comebacks': [],
        'weak_spots': [{'kind': 'theme_mismatch', 'text': 'no north dal or gravy for the roti'},
                       {'kind': 'heavy', 'text': 'pepper fry then ghee laddu'}],
        'data_doubts': [{'dish': 'drumstick_mango_pachadi', 'field': 'cuisine_family', 'tagged': 'north_indian',
                         'likely': 'south_indian', 'why': 'pachadi is a South Indian dish'}],
    },
}


def _with(**changes):
    reply = json.loads(json.dumps(GOOD))
    for path, value in changes.items():
        target = reply
        keys = path.split('__')
        for k in keys[:-1]:
            target = target[k]
        target[keys[-1]] = value
    return reply


@pytest.fixture
def on(monkeypatch):
    mod.reset_chef_read_cache_for_tests()
    monkeypatch.setattr(mod, 'CHEF_READ_ENABLED', True)
    monkeypatch.setattr(mod, 'API_KEY', 'test-key')
    return monkeypatch


def _script(monkeypatch, replies):
    """Make the model return `replies` in order; record every request."""
    calls = []

    def fake(system_prompt, contents, **kw):
        calls.append({'system': system_prompt, 'contents': json.loads(json.dumps(contents)), **kw})
        r = replies[min(len(calls), len(replies)) - 1]
        return r if (r is None or isinstance(r, str)) else json.dumps(r)

    monkeypatch.setattr(mod, '_post_model', fake)
    return calls


def _run(pack, **kw):
    return mod.explain_chef_read([pack], extras=EXTRAS, city_dish_names=CITY, **kw)[DATE]


def _facts(pack, **kw):
    return mod.build_chef_facts(pack, extras=EXTRAS, **kw)


class TestSwitches:
    def test_allowed_by_default_because_the_button_is_the_trigger(self):
        """The env var is a kill switch; asking is what runs it (see the endpoint tests)."""
        assert mod.CHEF_READ_ENABLED is True

    def test_the_kill_switch_returns_disabled_without_a_call(self, pack, monkeypatch):
        mod.reset_chef_read_cache_for_tests()
        monkeypatch.setattr(mod, 'CHEF_READ_ENABLED', False)
        monkeypatch.setattr(mod, 'API_KEY', 'test-key')
        calls = _script(monkeypatch, [GOOD])
        out = mod.explain_chef_read([pack])[DATE]
        assert out['source'] is None and out['reason'] == 'disabled' and not calls

    def test_no_key_never_calls_the_model(self, pack, monkeypatch):
        monkeypatch.setattr(mod, 'CHEF_READ_ENABLED', True)
        monkeypatch.setattr(mod, 'API_KEY', '')
        calls = _script(monkeypatch, [GOOD])
        assert _run(pack)['reason'] == 'no model key' and not calls

    def test_the_overview_is_untouched(self, pack, on):
        """Turning on the chef's read must not change the overview path."""
        _script(on, [GOOD])
        out = mod.explain_plan([pack])[DATE]
        assert out['reason'] == 'disabled' and out['bullets']


class TestTheLoop:
    def test_a_good_draft_is_accepted_first_time(self, pack, on):
        calls = _script(on, [GOOD])
        out = _run(pack)
        assert out['source'] == 'model' and out['reason'] == 'ok' and out['attempts'] == 1
        assert out['star']['dish'] == 'soya_chatpata_dry'
        assert len(calls) == 1 and calls[0]['model'] == mod.CHEF_READ_MODEL

    def test_problems_go_back_and_the_fix_is_accepted(self, pack, on):
        bad = _with(internal_read=GOOD['internal_read'] + ' The dal makhani would have fixed it.')
        calls = _script(on, [bad, GOOD])
        out = _run(pack)
        assert out['source'] == 'model' and out['attempts'] == 2
        assert out['reason'] == 'ok after 2 attempts'
        feedback = calls[1]['contents'][-1]['parts'][0]['text']
        assert 'dal makhani' in feedback and 'not on today' in feedback
        assert calls[1]['contents'][-2]['role'] == 'model'
        assert out['problems_by_attempt'][0] and out['problems_by_attempt'][1] == []

    def test_gives_up_after_max_attempts(self, pack, on):
        bad = _with(client_read='A classic north feast, kept fresh by our cooldown rule.')
        calls = _script(on, [bad])
        out = _run(pack)
        assert out['source'] is None and len(calls) == mod.CHEF_READ_MAX_ATTEMPTS
        assert out['reason'].startswith(f'rejected after {mod.CHEF_READ_MAX_ATTEMPTS} attempts')

    def test_a_transport_blip_spends_an_attempt_instead_of_the_day(self, pack, on):
        """Measured on a real 7-day plan: 1 call in 15 read-timed-out, and the
        day returned blank with two unused attempts standing by. A blip is not
        a bad draft, but it is not a reason to abandon a budget either."""
        calls = _script(on, [None, GOOD])
        out = _run(pack)
        assert out['source'] == 'model' and len(calls) == 2
        assert out['problems_by_attempt'][0] == ['no reply from the model (network)']

    def test_transport_failures_stay_inside_the_per_day_ceiling(self, pack, on):
        """The retry reuses the existing budget; it must not raise the cap."""
        calls = _script(on, [None])
        out = _run(pack)
        assert len(calls) == mod.CHEF_READ_MAX_ATTEMPTS
        assert out['source'] is None and out['reason'].startswith('model unavailable')

    def test_the_reason_names_the_failure_so_it_can_be_acted_on(self, pack, on):
        def fake(system_prompt, contents, outcome=None, **kw):
            if outcome is not None:
                outcome.update(kind='timeout', detail='ReadTimeout')
            return None
        on.setattr(mod, '_post_model', fake)
        assert _run(pack)['reason'] == 'model unavailable (ReadTimeout)'

    def test_a_rate_limit_is_terminal_and_is_not_retried(self, pack, on):
        """429 is the one failure that repeats on purpose. Retrying it inside
        the same second is rudeness with a delay, and spends the quota that
        caused it."""
        calls = []

        def fake(system_prompt, contents, outcome=None, **kw):
            calls.append(1)
            if outcome is not None:
                outcome.update(kind='rate_limited', detail='')
            return None
        on.setattr(mod, '_post_model', fake)
        out = _run(pack)
        assert out['reason'] == 'rate limited' and len(calls) == 1

    def test_invalid_json_gets_a_second_chance(self, pack, on):
        calls = _script(on, ['not json at all', GOOD])
        out = _run(pack)
        assert out['source'] == 'model' and len(calls) == 2
        assert 'valid JSON' in calls[1]['contents'][-1]['parts'][0]['text']

    def test_accepted_reads_are_cached(self, pack, on):
        calls = _script(on, [GOOD])
        _run(pack)
        out = _run(pack)
        assert out['reason'] == 'cache' and len(calls) == 1

    def test_later_days_are_told_how_earlier_days_opened(self, pack, on):
        day2 = json.loads(json.dumps(pack))
        day2['date'] = '2026-09-08'
        day2['weekday'] = 'Tuesday'
        calls = _script(on, [GOOD, _with(client_read='Easy Tuesday: ' + GOOD['client_read'])])
        mod.explain_chef_read([pack, day2], extras=EXTRAS, city_dish_names=CITY)
        facts2 = json.loads(calls[1]['contents'][0]['parts'][0]['text'])
        assert facts2['other_days_open_with'] and facts2['other_days_open_with'][0].startswith('Two good ways')


def _problems(pack, reply, **facts_kw):
    return mod.check_chef_read(reply, _facts(pack, **facts_kw), pack, CITY)


class TestTruthChecks:
    def test_the_good_draft_has_no_problems(self, pack):
        assert _problems(pack, GOOD) == []

    def test_no_template_is_required(self, pack):
        """A one-line day with no plates, no star and no comebacks is fine."""
        reply = _with(client_read='An easy day: steamed rice, dosakai sambar and rasam, with curd on the side.',
                      claims__plates=[], claims__star=None)
        assert _problems(pack, reply) == []

    def test_lowercase_off_menu_dish_is_caught(self, pack):
        reply = _with(internal_read=GOOD['internal_read'] + ' A paneer butter masala would help.')
        assert any('paneer butter masala' in p for p in _problems(pack, reply))

    def test_short_forms_of_todays_dishes_are_allowed(self, pack):
        reply = _with(client_read='Try the soya chatpata with the chapati, and finish with the motichur laddu.')
        assert _problems(pack, reply) == []

    def test_numbers_must_be_in_the_facts(self, pack):
        reply = _with(client_read='Back after 26 days: the soya chatpata.')
        assert any('26' in p for p in _problems(pack, reply))

    def test_health_claims_are_rejected(self, pack):
        reply = _with(client_read='A healthy plate today: rice, sambar and rasam.')
        assert any('health' in p for p in _problems(pack, reply))

    def test_underscores_are_rejected(self, pack):
        reply = _with(client_read='Pair jeera_chapati with the soya chatpata.')
        assert any('underscores' in p for p in _problems(pack, reply))


class TestJudgementGuards:
    def test_bread_with_rasam_is_vetoed(self, pack):
        reply = _with(claims__plates=[{'for': 'anyone', 'dishes': ['jeera_chapati', 'rasam']}])
        assert any('bread with rasam' in p for p in _problems(pack, reply))

    def test_pulao_with_a_dry_veg_is_a_normal_plate(self, pack):
        """The allow-list that rejected this was the lesson: veto absurdity only."""
        reply = _with(claims__plates=[{'for': 'veg', 'dishes': ['mint_pulao', 'soya_chatpata_dry', 'plain_curd_and_raita']}])
        assert _problems(pack, reply) == []

    def test_a_plate_needs_rice_or_bread(self, pack):
        reply = _with(claims__plates=[{'for': 'non-veg', 'dishes': ['chicken_pepper_fry', 'ghee_motichur_laddu']}])
        assert any('no rice or bread' in p for p in _problems(pack, reply))

    def test_star_basis_must_be_true(self, pack):
        reply = _with(claims__star={'dish': 'chicken_pepper_fry', 'basis': 'premium', 'why': 'richest dish'})
        assert any('not true for chicken pepper fry' in p for p in _problems(pack, reply))

    def test_plate_role_star_needs_two_plates(self, pack):
        reply = _with(claims__star={'dish': 'soya_chatpata_dry', 'basis': 'plate_role', 'why': 'ties plates'},
                      claims__plates=[{'for': 'north', 'dishes': ['jeera_chapati', 'soya_chatpata_dry']},
                                      {'for': 'veg', 'dishes': ['mint_pulao', 'soya_chatpata_dry']}])
        assert _problems(pack, reply) == []

    def test_comeback_needs_history_and_21_days(self, pack):
        reply = _with(claims__comebacks=['pumpkin_kootu'])
        assert any('not a comeback' in p for p in _problems(pack, reply))
        assert not any('not a comeback' in p
                       for p in _problems(pack, reply, recency={'pumpkin_kootu': 26}))

    def test_data_doubt_must_quote_the_tag_correctly(self, pack):
        reply = _with(claims__data_doubts=[{'dish': 'drumstick_mango_pachadi', 'field': 'cuisine_family',
                                            'tagged': 'south_indian', 'likely': 'south_indian', 'why': 'x'}])
        assert any('but the facts say' in p for p in _problems(pack, reply))


class TestTwoAudiences:
    def test_client_note_never_talks_about_the_machinery(self, pack):
        reply = _with(client_read='Our cooldown rule keeps the soya chatpata fresh.')
        assert any('cooldown' in p for p in _problems(pack, reply))

    def test_client_cannot_praise_a_theme_the_chef_note_criticises(self, pack):
        reply = _with(client_read='A true north spread today, with jeera chapati and soya chatpata.')
        assert any('praises the theme' in p for p in _problems(pack, reply))

    def test_client_cannot_call_a_heavy_day_light(self, pack):
        reply = _with(client_read='A light lunch: jeera chapati with the soya chatpata.')
        assert any('flags the day as heavy' in p for p in _problems(pack, reply))

    def test_known_problems_must_be_faced_internally(self, pack):
        pack['pairings']['gaps'] = ['chicken pepper fry is hot and nothing on the plate cools it']
        reply = _with(claims__weak_spots=[])
        problems = _problems(pack, reply)
        assert any('known_problems' in p for p in problems)

    def test_same_opening_as_another_day_is_sent_back(self, pack):
        problems = _problems(pack, GOOD, prior_openings=['Two good ways to eat today.'])
        assert any('opens the same way' in p for p in problems)


class TestFacts:
    def test_facts_carry_what_judgement_needs(self, pack):
        f = _facts(pack, recency={'pumpkin_kootu': 26}, region='Tamil Nadu')
        by = {d['name']: d for d in f['dishes']}
        assert by['soya_chatpata_dry']['premium'] is True
        assert by['pumpkin_kootu']['state_origin'] == 'Tamil Nadu'
        assert by['pumpkin_kootu']['days_since_served'] == 26
        assert f['has_history'] is True and f['regional_day'] == 'Tamil Nadu'

    def test_pinned_dishes_are_marked(self, pack):
        pack['provenance'].append({'dish': 'rasam', 'slot': 'rasam', 'reason': 'client_constant', 'detail': 'pinned'})
        by = {d['name']: d for d in _facts(pack)['dishes']}
        assert by['rasam']['pinned'] is True and by['jeera_chapati']['pinned'] is False


class TestEveryRejectionRuleIsInThePrompt:
    """A check the prompt never states is a draft spent teaching it.

    The module's own tuning note says a limit in the prompt without a matching
    check goes unenforced — this is the mirror of it, and it is the one that
    cost money. Measured on a real 7-day plan: 16 model calls, ZERO days
    accepted first draft, and almost every rejection was a rule the model was
    never told. Naming them took the same plan to 9-11 calls with most days
    accepted first time. So each word list the checks reject on is asserted to
    appear in the prompt, and a new check with no prompt line fails here
    instead of quietly costing a retry per day forever.
    """

    def test_the_praise_words_are_named(self):
        for word in ('perfect', 'balanced', 'flawless'):
            assert word in mod.CHEF_READ_SYSTEM_PROMPT, word

    def test_the_contradiction_words_are_named(self):
        for word in ('light', 'lighter', 'easy on the stomach',
                     'varied', 'variety', 'something different'):
            assert word in mod.CHEF_READ_SYSTEM_PROMPT, word

    def test_the_theme_praise_adjectives_are_named(self):
        for word in ('classic', 'true', 'authentic', 'proper', 'real', 'pure'):
            assert f'"{word}"' in mod.CHEF_READ_SYSTEM_PROMPT, word

    def test_a_plate_is_told_it_needs_a_carb(self):
        p = mod.CHEF_READ_SYSTEM_PROMPT
        assert 'needs a rice or a bread' in p
        # and told to take it from today's menu, or the fix trades one
        # rejection for another: the first wording said "add the chapati"
        # and the model added a chapati the day did not have.
        assert "TODAY'S list of dishes" in p
        for word in mod._CARB_WORDS:
            assert word in p, word

    def test_the_opening_rule_says_how_much_must_differ(self):
        """"do not open the way other days opened" is not actionable; the
        check compares the first FOUR words."""
        assert 'FIRST FOUR' in mod.CHEF_READ_SYSTEM_PROMPT
        assert 'other_days_open_with' in mod.CHEF_READ_SYSTEM_PROMPT


class TestTheReplyIsFoundInTheReply:
    """A thinking model puts its answer after its reasoning.

    Every model this API key can reach is a thinking model, and the one that
    used to be the default (`gemma-4-31b-it`) writes ~3,900 characters of
    bulleted reasoning before the JSON — even with
    `responseMimeType: application/json`. Fence-stripping alone rejected that
    as malformed, so all three drafts burned and the day silently had no read.
    Measured against a real key, not supposed.
    """

    PREAMBLE = ('*   Date: 2026-09-07 (Monday)\n'
                '    *   Pachadi is tagged north - *wait, that is southern*\n'
                '    *   Shape to return: {"client_read": "...", ...}\n')

    def test_a_clean_reply_is_unchanged(self):
        assert mod._parse_reply('{"a": 1}') == {'a': 1}
        assert mod._parse_reply('```json\n{"a": 1}\n```') == {'a': 1}

    def test_reasoning_before_the_json_is_skipped(self):
        got = mod._parse_reply(self.PREAMBLE + json.dumps(GOOD))
        assert got == GOOD

    def test_a_nested_object_never_wins_over_the_whole_reply(self):
        """The first version of this returned a `data_doubts` entry: scanning
        every brace and keeping the LAST match picks the innermost one,
        because a nested brace comes after its parent's."""
        got = mod._parse_reply(self.PREAMBLE + json.dumps(GOOD))
        assert set(got) == {'client_read', 'internal_read', 'claims'}
        assert got['claims']['data_doubts'][0]['dish'] == 'drumstick_mango_pachadi'

    def test_a_whole_read_survives_the_round_trip(self, pack):
        assert _problems(pack, mod._parse_reply(self.PREAMBLE + json.dumps(GOOD))) == []

    def test_nothing_parseable_is_still_None(self):
        assert mod._parse_reply('I could not do that.') is None
        assert mod._parse_reply('[1, 2, 3]') is None
        assert mod._parse_reply('') is None


class TestRoomToWrite:
    """Ceilings are generous and stated, so a rich day is never choked."""

    def test_the_prompt_states_the_word_ceilings(self):
        p = mod.CHEF_READ_SYSTEM_PROMPT
        assert f'under {mod.CLIENT_MAX_WORDS} words' in p
        assert f'under {mod.INTERNAL_MAX_WORDS} words' in p
        assert '<CLIENT_MAX_WORDS>' not in p and '<INTERNAL_MAX_WORDS>' not in p

    def test_defaults_leave_room_for_a_full_read(self):
        assert mod.CLIENT_MAX_WORDS >= 200 and mod.INTERNAL_MAX_WORDS >= 350
        assert mod.CHEF_READ_MAX_TOKENS >= 2500

    def test_a_long_guest_note_is_accepted(self, pack):
        long_note = ' '.join([GOOD['client_read']] * 4)
        assert 140 < len(long_note.split()) < mod.CLIENT_MAX_WORDS
        assert _problems(pack, _with(client_read=long_note)) == []

    def test_the_ceiling_can_be_changed(self, pack, monkeypatch):
        monkeypatch.setattr(mod, 'CLIENT_MAX_WORDS', 20)
        assert any('too long' in p for p in _problems(pack, GOOD))

    def test_a_cut_off_reply_is_told_it_was_cut_off(self, pack, on):
        cut = json.dumps(GOOD)[:300]
        calls = _script(on, [cut, GOOD])
        out = _run(pack)
        assert out['source'] == 'model' and out['attempts'] == 2
        assert 'cut off' in calls[1]['contents'][-1]['parts'][0]['text']

    def test_the_request_asks_for_the_configured_token_room(self, pack, on):
        calls = _script(on, [GOOD])
        _run(pack)
        assert calls[0]['max_tokens'] == mod.CHEF_READ_MAX_TOKENS


class TestToneIsChecked:
    """"No headings, no lists, no labels" was a prompt line nothing enforced.

    The module's own tuning note says a limit in the prompt without a matching
    check either wastes retries or goes unenforced, and this is the one that
    shows: asked for prose, a model reaches for a bulleted list the moment a
    day has three things worth saying — and a list is what makes a note
    skimmed rather than read.
    """

    def test_a_bulleted_draft_is_sent_back(self, pack):
        reply = _with(internal_read='- No north gravy for the roti.\n- Heavy finish.')
        assert any('list or a heading' in p for p in _problems(pack, reply))

    def test_a_numbered_draft_is_sent_back(self, pack):
        reply = _with(client_read='1. Chapati with the soya chatpata.\n2. Rice with sambar.')
        assert any('list or a heading' in p for p in _problems(pack, reply))

    def test_a_heading_is_sent_back(self, pack):
        reply = _with(internal_read="## The plate\nNothing wet for the roti.")
        assert any('list or a heading' in p for p in _problems(pack, reply))

    def test_a_label_echoed_from_the_schema_is_sent_back(self, pack):
        reply = _with(internal_read='Weak spots: nothing wet for the roti, and a heavy finish.')
        assert any('uses the label' in p for p in _problems(pack, reply))

    def test_a_field_name_mid_sentence_is_caught_too(self, pack):
        """Not line-anchored: a schema word reads as leaked plumbing wherever
        it lands, not only at the start of a line."""
        reply = _with(internal_read='As internal_read notes, the dal is a kootu.')
        assert any('uses the label' in p for p in _problems(pack, reply))

    def test_ordinary_prose_is_left_alone(self, pack):
        """The guard has to be narrow or it rejects good writing. The first
        draft of it flagged "An easy day:" — a capitalised word before a colon
        is a sentence, not a label — and the suite above caught that."""
        reply = _with(client_read='Two good ways to eat today - roti or rice. '
                                  'The soya chatpata is the pick.')
        assert _problems(pack, reply) == []

    def test_a_colon_in_a_sentence_is_not_a_label(self, pack):
        reply = _with(client_read='An easy day: steamed rice, dosakai sambar '
                                  'and rasam, with curd on the side.')
        assert _problems(pack, reply) == []

    def test_a_hyphenated_dish_name_is_not_a_bullet(self, pack):
        reply = _with(internal_read=GOOD['internal_read'].replace(
            'The pachadi looks wrongly marked north.',
            'The do-pyaza style would have suited it better.'))
        assert not any('list or a heading' in p for p in _problems(pack, reply))


def test_the_prompt_and_its_readable_copy_have_not_drifted():
    """`docs/chef_read_prompt.md` says it is the readable copy of
    `CHEF_READ_SYSTEM_PROMPT` and that the two change together. Nothing made
    that true. A doc describing a prompt the model is not being given is worse
    than no doc, because it is the one somebody reads before tuning.
    """
    import pathlib
    import re
    doc = (pathlib.Path(__file__).resolve().parents[2]
           / 'docs' / 'chef_read_prompt.md').read_text(encoding='utf-8')
    block = re.search(r'```text\n(.*?)\n```', doc, re.S)
    assert block, 'the doc no longer carries the prompt in a ```text block'
    # The two word ceilings are settings interpolated into the prompt, so they
    # are masked on both sides: the doc shows the defaults, and a deployment
    # that raised them must not make this read as drift.
    norm = lambda s: re.sub(r'under \d+ words', 'under N words',      # noqa: E731
                            re.sub(r'\s+', ' ', s).strip())
    assert norm(block.group(1)) == norm(mod.CHEF_READ_SYSTEM_PROMPT)
    assert mod.CHEF_READ_PROMPT_VERSION in doc, (
        'the doc names a different prompt version than the module')
