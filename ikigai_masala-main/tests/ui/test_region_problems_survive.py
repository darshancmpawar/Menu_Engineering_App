"""A regional pick the solve could not honour reaches the screen.

The server already decides this correctly and says why: ask for a south
Indian region on a Chinese-themed day and `/plan` answers 200 with an empty
`region_days` and a `region_problems` entry explaining that the theme filter
removes every dish of that region from the main slots before the regional
floor is read.

`flatten_result` carried `region_days` and `regional_dishes` out of that
response and **dropped `region_problems`**. The Apply-to-an-existing-plan path
collected them separately, so the failure was invisible on exactly one route:
pick a region in the sidebar, press Generate, and get a menu with no regional
dishes and nothing on screen saying why. That is indistinguishable from the
feature being broken, which is how it was reported.

Both halves are asserted — the problem survives, and an honoured pick still
carries its region and dishes — because a `flatten_result` that returned
everything under one key would pass the first assertion alone.
"""

from __future__ import annotations

import pytest

from ui.planner_view import flatten_result

_SOLUTION = {'2026-11-03': {'day_type': 'chinese', 'is_working_day': True,
                            'items': {'rice': {'item_base': 'veg_fried_rice',
                                               'item': 'veg_fried_rice(Y)'}}}}


def test_a_refused_region_survives_flattening():
    """The bug. Without this the explanation dies between server and screen."""
    problem = {'date': '2026-11-03', 'region': 'Karnataka',
               'reason': 'theme_conflict', 'theme': 'chinese',
               'message': 'Karnataka is south_indian and this day is themed '
                          'chinese.'}
    out = flatten_result({'solution': _SOLUTION, 'region_problems': [problem]})
    assert out['region_problems'] == [problem], (
        'the server explained why the regional pick was refused and the '
        'planner threw it away — the menu then looks like the feature is '
        'broken rather than like the day said no')


def test_an_honoured_region_still_carries_its_dishes():
    """The negative half: the three regional keys stay distinct.

    `regions` is what IS in force, `regional_dishes` is which cells carry it,
    `region_problems` is what was refused. Collapsing any two would make a
    refused pick read as an applied one.
    """
    out = flatten_result({
        'solution': _SOLUTION,
        'region_days': {'2026-11-05': 'Karnataka'},
        'regional_dishes': {'2026-11-05': ['bisi_bele_bath']},
    })
    assert out['regions'] == {'2026-11-05': 'Karnataka'}
    assert out['regional_dishes'] == {'2026-11-05': ['bisi_bele_bath']}
    assert out['region_problems'] == []


def test_a_plan_with_no_regional_pick_reports_nothing():
    """Absent, not null: the picker iterates this list every render."""
    out = flatten_result({'solution': _SOLUTION})
    assert out['region_problems'] == []


if __name__ == '__main__':      # a runnable check without pytest
    raise SystemExit(pytest.main([__file__, '-q']))
