"""The component's dish-name highlighter, run through node when there is one.

`ui/menu_table/index.html` is a deliberately node-free static component — `pip
install` is the whole toolchain — so this is a SKIP rather than a dependency.
Where node exists (CI images, most dev boxes) it runs, and it reads the
functions out of the shipped HTML rather than a copy, so the two cannot drift.

It earned its place: the first version of the regex guarded only the left word
boundary, so a `Dal` cell painted the front of "Dalgona" and nothing said so.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent / "js" / "colour_dishes.test.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="no node on this box")
def test_colour_dishes():
    r = subprocess.run([shutil.which("node"), str(SCRIPT)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
