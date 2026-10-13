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

JS_DIR = pathlib.Path(__file__).parent / 'js'


@pytest.mark.skipif(shutil.which('node') is None, reason='no node on this box')
@pytest.mark.parametrize('name', ['pick_results.test.js', 'pick_focus.test.js'])
def test_pick_component_behaviour(name):
    out = subprocess.run(['node', str(JS_DIR / name)],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
