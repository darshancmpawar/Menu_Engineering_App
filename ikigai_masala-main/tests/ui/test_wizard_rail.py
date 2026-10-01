"""The editor's wizard rail — which step is done, which one is live.

The rail is the only thing on the page saying the three steps are a SEQUENCE.
They all render stacked, so without it a long client has no sense of place and
no way to tell a step they finished from one they scrolled past.

What is tested here is the DECISION, not the HTML. Two things have to hold or
the rail is worse than nothing:

  * a step is done only when the editor's own state says so. A rail that counts
    clicks shows a tick for work that would not save, which is a lie told
    confidently;
  * at most ONE step is live. Two highlighted steps is precisely the confusion
    a progress rail exists to remove.
"""

from __future__ import annotations

from customisation.main import rail_steps


def _state(*args, **kw):
    return {n: cls for n, _t, _m, cls in rail_steps(*args, **kw)}


def _meta(*args, **kw):
    return {n: m for n, _t, m, _c in rail_steps(*args, **kw)}


def test_a_fresh_editor_points_at_the_client_step():
    assert _state("", "", 0, False) == {1: "now", 2: "", 3: ""}


def test_naming_a_client_completes_one_and_moves_the_pointer():
    assert _state("DXC", "", 0, False) == {1: "done", 2: "now", 3: ""}


def test_choosing_a_layout_moves_it_again():
    assert _state("DXC", "single", 1, False) == {1: "done", 2: "done", 3: "now"}


def test_everything_done_leaves_nothing_live():
    """Correct rather than an oversight: there is no next step to point at."""
    assert _state("DXC", "multi", 3, True) == {1: "done", 2: "done", 3: "done"}


def test_exactly_one_step_is_ever_live():
    """The guarantee. Every reachable combination, not a sampled few."""
    for client in ("", "DXC"):
        for mode in ("", "single", "multi"):
            for ready in (False, True):
                got = [c for _n, _t, _m, c in
                       rail_steps(client, mode, 2, ready)].count("now")
                assert got <= 1, (client, mode, ready, got)


def test_a_later_step_cannot_be_live_while_an_earlier_one_is_unfinished():
    """Readiness can run ahead of the client name — the editor seeds a default
    counter before anyone types one. The rail must still point at the gap."""
    assert _state("", "single", 1, True)[1] == "now"


def test_the_meta_line_says_what_was_actually_chosen():
    assert _meta("DXC", "multi", 4, False)[2] == "4 counters"
    assert _meta("DXC", "single", 1, False)[2] == "single counter"
    assert _meta("", "", 0, False)[2] == "not chosen yet"


def test_an_unnamed_client_says_so_rather_than_going_blank():
    """A blank cell reads as a rendering bug; "none picked yet" reads as a
    step waiting for you."""
    assert _meta("", "", 0, False)[1] == "none picked yet"


if __name__ == "__main__":  # a runnable check without pytest
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
