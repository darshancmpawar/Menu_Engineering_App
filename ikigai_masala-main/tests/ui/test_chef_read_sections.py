"""The planner's "Chef's read": one heading, two sections, guests then kitchen."""
from ui.formatters import chef_read_sections, chef_read_status

READ = {
    'source': 'model', 'reason': 'ok',
    'client_read': 'Two good ways to eat today.',
    'internal_read': 'Says north on paper, but the south plate is the complete one.',
    'star': {'dish': 'soya_chatpata_dry', 'basis': 'premium', 'why': 'the premium veg dish'},
    'data_doubts': [{'dish': 'drumstick_mango_pachadi', 'field': 'cuisine_family',
                     'tagged': 'north_indian', 'likely': 'south_indian', 'why': 'pachadi is southern'}],
}


def test_two_sections_guests_first():
    secs = chef_read_sections(READ)
    assert [s['key'] for s in secs] == ['guests', 'kitchen']
    assert [s['title'] for s in secs] == ['For guests', 'For the kitchen']
    assert secs[0]['text'] == READ['client_read'] and secs[1]['text'] == READ['internal_read']


def test_the_star_goes_with_guests_and_doubts_with_the_kitchen():
    guests, kitchen = chef_read_sections(READ)
    assert guests['notes'] == ['Star of the day: Soya Chatpata Dry (the premium veg dish)']
    assert 'Drumstick Mango Pachadi' in kitchen['notes'][0] and 'north indian' in kitchen['notes'][0]
    assert not any('Pachadi' in n for n in guests['notes'])


def test_no_star_and_no_doubts_means_no_notes():
    secs = chef_read_sections(dict(READ, star=None, data_doubts=[]))
    assert all(s['notes'] == [] for s in secs)


def test_a_rejected_or_missing_read_shows_nothing():
    assert chef_read_sections(None) == []
    assert chef_read_sections({'source': None, 'reason': 'rejected after 3 attempts: x'}) == []


def test_nothing_is_said_until_the_chef_is_asked():
    for chef in (None, {'source': None, 'reason': 'disabled'},
                 {'source': None, 'reason': 'no model key'}):
        assert chef_read_status(chef) is None


def test_once_asked_a_missing_day_says_why():
    assert chef_read_status(READ, asked=True) is None
    assert 'switched off' in chef_read_status({'source': None, 'reason': 'disabled'}, asked=True)
    # Each cause says what to DO about it; they used to share one line.
    assert 'EXPLAIN_LLM_API_KEY' in chef_read_status({'source': None, 'reason': 'no model key'}, asked=True)
    assert 'rate limit' in chef_read_status({'source': None, 'reason': 'rate limited'}, asked=True)
    timed_out = chef_read_status({'source': None, 'reason': 'model unavailable (ReadTimeout)'}, asked=True)
    assert 'ReadTimeout' in timed_out and 'Every other day is unaffected' in timed_out
    assert 'fact checks' in chef_read_status({'source': None, 'reason': 'rejected after 3 attempts: x'}, asked=True)
    assert chef_read_status(None, asked=True)
