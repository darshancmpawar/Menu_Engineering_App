"""Run the in-cell search's JS through node where there is one.

Same pattern as `test_colour_dishes_js.py`: the assertions live in the `.js`
file so they read the SHIPPED component source, and this wrapper only makes
them visible to pytest.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

TEST_JS = pathlib.Path(__file__).parent / 'js' / 'pick_results.test.js'


@pytest.mark.skipif(shutil.which('node') is None, reason='no node on this box')
def test_pick_search_matching_ranking_and_locks():
    out = subprocess.run(['node', str(TEST_JS)], capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
