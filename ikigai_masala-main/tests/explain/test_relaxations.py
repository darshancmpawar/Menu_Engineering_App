"""The honesty channel: the solver's own "I could not fully enforce this" lines.

Sixteen sites in the rule layer degrade rather than fail, and every one of them
used to say so only to a log. This is the wiring that carries them into the
explanation, and the tests that stop it going quiet.

Two failure modes are engineered against here and both are silent, which is why
they get tests rather than trust:

  * a deployment logging at WARNING drops the eleven INFO relaxations before any
    handler runs — nothing raises, the pack simply lists none;
  * two concurrent solves share one logger, so without a thread filter one
    client's explanation cites another client's relaxed rule.
"""

from __future__ import annotations

import ast
import logging
import pathlib
import re
import threading

import pytest

from src.menu_rules.relaxations import (
    RELAXATION, RULES_LOGGER, RelaxationCapture,
)

RULES_DIR = pathlib.Path(__file__).resolve().parents[2] / 'src' / 'menu_rules'


@pytest.fixture
def log():
    return logging.getLogger(RULES_LOGGER + '.test_probe')


@pytest.fixture(autouse=True)
def _no_leaked_captures():
    """A capture left un-exited makes every LATER one in the process deaf.

    The refcount is module state, so one test failing part-way through a
    lifecycle would silently break the tests after it — and they would fail
    with "captured nothing", pointing at the wrong code. Assert it here so the
    leak is reported where it happened.
    """
    yield
    from src.menu_rules import relaxations as mod
    depth, mod._depth = mod._depth, 0
    logging.getLogger(RULES_LOGGER).setLevel(logging.NOTSET)
    assert depth == 0, f'{depth} capture(s) left un-exited'


class TestWhatCounts:
    def test_a_stamped_record_is_captured(self, log):
        with RelaxationCapture() as cap:
            log.info('%s: floor relaxed for day %d', 'my_rule', 3,
                     extra={RELAXATION: 'my_rule'})
        assert cap.records == [{'rule': 'my_rule',
                                'detail': 'floor relaxed for day 3',
                                'occurrences': 1,
                                'samples': ['floor relaxed for day 3']}]

    def test_the_rule_name_is_not_printed_twice(self, log):
        """Messages read "<rule>: <what happened>" and the name is its own
        field, so the prefix is stripped rather than rendered again."""
        with RelaxationCapture() as cap:
            log.info('%s: capped', 'r', extra={RELAXATION: 'r'})
        assert cap.records[0]['detail'] == 'capped'

    def test_an_ordinary_log_line_is_not_a_relaxation(self, log):
        """The reason this is a stamped field and not a level convention: the
        rules tree carries INFO and WARNING lines that are nothing of the kind
        (a malformed rule config skipped at load time)."""
        with RelaxationCapture() as cap:
            log.info('Loaded %d menu rule(s)', 42)
            log.warning("Skipping invalid rule 'x': validate_config() failed")
        assert cap.records == []

    def test_nothing_is_captured_after_the_block(self, log):
        with RelaxationCapture() as cap:
            pass
        log.info('%s: too late', 'r', extra={RELAXATION: 'r'})
        assert cap.records == []


class TestTheDedup:
    def test_one_entry_per_message_shape_with_a_count(self, log):
        """A 25-day plan relaxing a daily floor emits one record per day. A
        chef needs the fact once, with a number — not twenty-five lines."""
        with RelaxationCapture() as cap:
            for day in range(25):
                log.info('%s: day %d floor relaxed', 'r', day,
                         extra={RELAXATION: 'r'})
        assert len(cap.records) == 1
        assert cap.records[0]['occurrences'] == 25
        assert cap.records[0]['detail'] == 'day 0 floor relaxed'

    def test_different_shapes_from_one_rule_stay_separate(self, log):
        with RelaxationCapture() as cap:
            log.info('%s: floor relaxed', 'r', extra={RELAXATION: 'r'})
            log.info('%s: ban skipped', 'r', extra={RELAXATION: 'r'})
        assert len(cap.records) == 2

    def test_the_varying_half_is_kept_not_collapsed(self, log):
        """The count alone is not actionable. `selector_frequency` logs per
        day, so which days could not be filled is the whole point — "Tuesday
        and Thursday could not fit the second dessert" is something a kitchen
        acts on, "this happened 25 times" is not."""
        with RelaxationCapture() as cap:
            for day in (3, 5, 9):
                log.info('%s: day %d floor relaxed', 'r', day,
                         extra={RELAXATION: 'r'})
        rec = cap.records[0]
        assert rec['occurrences'] == 3
        assert rec['samples'] == ['day 3 floor relaxed', 'day 5 floor relaxed',
                                  'day 9 floor relaxed']

    def test_samples_are_capped_so_a_long_plan_is_not_a_wall_of_text(self, log):
        from src.menu_rules.relaxations import MAX_SAMPLES
        with RelaxationCapture() as cap:
            for day in range(30):
                log.info('%s: day %d floor relaxed', 'r', day,
                         extra={RELAXATION: 'r'})
        rec = cap.records[0]
        assert rec['occurrences'] == 30
        assert len(rec['samples']) == MAX_SAMPLES

    def test_identical_renderings_are_not_listed_twice(self, log):
        with RelaxationCapture() as cap:
            for _ in range(4):
                log.info('%s: capped to %d', 'r', 1, extra={RELAXATION: 'r'})
        assert cap.records[0]['samples'] == ['capped to 1']

    def test_grouping_is_on_the_format_string_not_the_prose(self, log):
        """`record.msg` is pre-interpolation, so the grouping key is the thing
        that was relaxed. Two rules wording it identically stay apart."""
        with RelaxationCapture() as cap:
            log.info('%s: capped to %d', 'a', 1, extra={RELAXATION: 'a'})
            log.info('%s: capped to %d', 'b', 2, extra={RELAXATION: 'b'})
        assert {r['rule'] for r in cap.records} == {'a', 'b'}


class TestTheSilentFailureModes:
    def test_an_info_relaxation_survives_a_warning_level_deployment(self, log):
        """The one that would capture NOTHING and never say so. Eleven of the
        sixteen sites are `logger.info`."""
        tree = logging.getLogger(RULES_LOGGER)
        before = tree.level
        tree.setLevel(logging.WARNING)
        try:
            with RelaxationCapture() as cap:
                log.info('%s: relaxed', 'r', extra={RELAXATION: 'r'})
            assert len(cap.records) == 1
            assert tree.level == logging.WARNING, 'level not restored'
        finally:
            tree.setLevel(before)

    def test_the_level_is_restored_even_when_the_solve_raises(self, log):
        tree = logging.getLogger(RULES_LOGGER)
        tree.setLevel(logging.WARNING)
        try:
            with pytest.raises(RuntimeError):
                with RelaxationCapture():
                    raise RuntimeError('INFEASIBLE')
            assert tree.level == logging.WARNING
        finally:
            tree.setLevel(logging.NOTSET)

    def test_the_exception_is_not_swallowed(self):
        """A capture that ate an INFEASIBLE would turn a reportable conflict
        into a menu-shaped hole."""
        with pytest.raises(ValueError):
            with RelaxationCapture():
                raise ValueError('boom')

    def test_two_overlapping_captures_do_not_strand_the_level(self, log):
        """The refcount, in both directions.

        Restoring on the FIRST exit goes deaf: the capture still running stops
        seeing INFO and reports no relaxations. Restoring "the level I saw on
        the way in" on the LAST exit leaves the tree at INFO forever, because
        the second capture saw the level the first had already lowered. Only
        one entry and one exit may move it.
        """
        tree = logging.getLogger(RULES_LOGGER)
        tree.setLevel(logging.WARNING)
        outer, inner = RelaxationCapture(), RelaxationCapture()
        try:
            outer.__enter__()
            inner.__enter__()
            outer.__exit__(None, None, None)
            assert tree.level == logging.INFO, 'restored while one is still live'
            inner.__exit__(None, None, None)
            assert tree.level == logging.WARNING, 'left lowered'
        finally:
            tree.setLevel(logging.NOTSET)

    def test_capturing_does_not_flood_the_operator_s_log(self, log):
        """The cost of lowering the level, and why `_Bridge` exists.

        `api/logging_config.py` gives its stderr handler no level of its own,
        so a deployment at WARNING has an ancestor handler that emits whatever
        reaches it. Lowering this tree to INFO without care would print every
        relaxation and every loader INFO for the duration of every solve — a
        diagnostic feature making the production log worse.
        """
        seen = []

        class _Sink(logging.Handler):
            def emit(self, record):
                seen.append((record.levelno, record.getMessage()))

        root = logging.getLogger()
        sink = _Sink()                      # NOTSET, like the real stderr one
        root.addHandler(sink)
        tree = logging.getLogger(RULES_LOGGER)
        tree.setLevel(logging.WARNING)
        try:
            with RelaxationCapture() as cap:
                log.info('%s: relaxed', 'r', extra={RELAXATION: 'r'})
                log.info('Loaded %d menu rule(s)', 57)
                log.warning('Skipping invalid rule')
            assert len(cap.records) == 1, 'the capture went deaf'
            levels = [lv for lv, _ in seen]
            assert logging.INFO not in levels, (
                f'INFO leaked to an ancestor handler: {seen}')
            assert logging.WARNING in levels, (
                'a genuine WARNING stopped reaching the operator')
        finally:
            root.removeHandler(sink)
            tree.setLevel(logging.NOTSET)

    def test_an_already_verbose_deployment_is_unchanged(self, log):
        """At INFO the operator was already seeing these lines; the bridge must
        not start hiding them."""
        seen = []

        class _Sink(logging.Handler):
            def emit(self, record):
                seen.append(record.getMessage())

        root = logging.getLogger()
        sink = _Sink()
        root.addHandler(sink)
        tree = logging.getLogger(RULES_LOGGER)
        tree.setLevel(logging.INFO)
        try:
            with RelaxationCapture():
                log.info('%s: relaxed', 'r', extra={RELAXATION: 'r'})
            assert any('relaxed' in m for m in seen), seen
        finally:
            root.removeHandler(sink)
            tree.setLevel(logging.NOTSET)

    def test_propagation_is_restored_afterwards(self, log):
        tree = logging.getLogger(RULES_LOGGER)
        before = tree.propagate
        with RelaxationCapture():
            pass
        assert tree.propagate == before
        assert not [h for h in tree.handlers
                    if type(h).__name__ == '_Bridge'], 'bridge left attached'

    def test_a_concurrent_solve_does_not_leak_into_this_one(self, log):
        """`@solver_gate` runs two solves at once by design, and every handler
        on a logger sees every record. Without the thread filter, one client's
        explanation lists another client's relaxed rule."""
        done = threading.Event()
        with RelaxationCapture() as mine:
            def other_request():
                log.info('%s: not yours', 'their_rule',
                         extra={RELAXATION: 'their_rule'})
                done.set()
            t = threading.Thread(target=other_request)
            t.start()
            done.wait(timeout=5)
            t.join(timeout=5)
            log.info('%s: mine', 'my_rule', extra={RELAXATION: 'my_rule'})
        assert [r['rule'] for r in mine.records] == ['my_rule']


class TestARealRuleRelaxing:
    def test_a_starved_slot_reports_its_dropped_uniqueness(self):
        """Not a stub: `unique_items` on a slot with fewer distinct dishes than
        cells. That relaxation is the one the client's "no repeats, hard and
        strict" rule makes most consequential, so it must reach the reader."""
        import datetime as dt
        import pandas as pd
        from ortools.sat.python import cp_model
        from src.menu_rules.unique_items_menu_rule import UniqueItemsMenuRule
        from src.solver.menu_solver import _Cell

        model = cp_model.CpModel()
        names = ['dish_a', 'dish_b']
        cells = []
        for day in range(4):                     # 4 days, 2 dishes -> starved
            rows = [pd.Series({'item': d, 'course_type': 'veg_gravy'})
                    for d in names]
            cell = _Cell(day, dt.date(2026, 9, 7) + dt.timedelta(days=day),
                         'veg_gravy__1', 'veg_gravy',
                         pd.DataFrame(rows), [False] * len(names))
            cell.cand_rows = rows
            cell.x_vars = [model.NewBoolVar(f'd{day}_{d}') for d in names]
            cells.append(cell)
        ctx = {'cells': cells,
               'item_to_vars': {d: [] for d in names}}

        rule = UniqueItemsMenuRule({'name': 'unique_items',
                                    'type': 'unique_items'})
        with RelaxationCapture() as cap:
            rule.apply(model, {}, None, ctx)

        assert [r['rule'] for r in cap.records] == ['unique_items']
        assert 'may repeat' in cap.records[0]['detail']


# ---------------------------------------------------------------------------
# The guard. A relaxation added later without the stamp is invisible — the
# menu still plans, the explanation just quietly stops mentioning it.
# ---------------------------------------------------------------------------

RELAXATION_WORDS = re.compile(
    r'\brelax|\bcapp(?:ed|ing)\b|\bskipp(?:ed|ing)\b|\bdropp(?:ed|ing)\b'
    r'|\binert\b|\binstead of\b', re.IGNORECASE)

# Log lines that match the vocabulary and are deliberately NOT relaxations:
# they are load-time config errors, not a rule under-enforced during a solve.
# There is nothing for a chef to act on and no menu they describe.
NOT_A_RELAXATION = {
    ('menu_rule_loader.py', "Skipping invalid %s '%s' (type=%s): %s"),
    ('menu_rule_loader.py',
     "Skipping invalid %s '%s' (type=%s): validate_config() returned False"),
    ('menu_rule_loader.py',
     '%s: expected an object at the top level, got %s — skipped'),
}


def _logger_calls():
    """Every `logger.<level>(...)` in the rules tree, with its format string."""
    for path in sorted(RULES_DIR.glob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if not (isinstance(fn, ast.Attribute)
                    and isinstance(fn.value, ast.Name)
                    and fn.value.id == 'logger'
                    and fn.attr in ('debug', 'info', 'warning', 'error')):
                continue
            if not node.args:
                continue
            first = node.args[0]
            if not (isinstance(first, ast.Constant)
                    and isinstance(first.value, str)):
                continue
            stamped = any(kw.arg == 'extra' for kw in node.keywords)
            yield path.name, node.lineno, first.value, stamped


# Every degradation site in the rule layer, pinned. This is the STRUCTURAL
# half of the guard and the one that cannot be fooled by phrasing: adding or
# removing a site fails the test and forces a deliberate update here, whatever
# words the new message happens to use.
#
# The lexical scan below is a second net for the specific mistake of writing a
# new relaxation and forgetting the stamp — it would leave this count
# unchanged, because an unstamped site is invisible to a structural count. The
# two catch different errors and neither replaces the other.
STAMPED_SITES = 16


class TestEveryRelaxationIsStamped:
    def test_the_number_of_stamped_sites_is_pinned(self):
        """Structural, not lexical. A new degradation site changes this number
        whatever it is worded like, so it cannot slip past a vocabulary gap —
        the way `chuteny` slipped past `remove_generic_rows.py` by not being
        spelled like the word it searched for."""
        stamped = [f'{n}:{l}' for n, l, _m, s in _logger_calls() if s]
        assert len(stamped) == STAMPED_SITES, (
            f'{len(stamped)} stamped relaxation sites, expected '
            f'{STAMPED_SITES}. If you added or removed one deliberately, '
            f'update STAMPED_SITES. Sites: {stamped}')

    def test_the_scan_finds_the_known_sites(self):
        """Guard the guard: a regex that matches nothing would pass the test
        below without checking anything."""
        found = [c for c in _logger_calls() if RELAXATION_WORDS.search(c[2])]
        assert len(found) >= STAMPED_SITES, [f'{c[0]}:{c[1]}' for c in found]

    def test_no_relaxation_shaped_line_is_missing_its_stamp(self):
        missing = [
            f'{name}:{lineno} {msg[:60]!r}'
            for name, lineno, msg, stamped in _logger_calls()
            if RELAXATION_WORDS.search(msg) and not stamped
            and (name, msg) not in NOT_A_RELAXATION
        ]
        assert not missing, (
            'these log lines describe a relaxed rule but carry no '
            f'extra={{RELAXATION: ...}}, so no explanation will mention '
            f'them: {missing}')

    def test_the_allow_list_still_names_real_lines(self):
        """An entry left behind after its line was reworded would silently
        stop excusing anything — and could start excusing the wrong line."""
        live = {(name, msg) for name, _l, msg, _s in _logger_calls()}
        assert NOT_A_RELAXATION <= live, NOT_A_RELAXATION - live

    def test_every_stamped_site_stamps_the_rule_name(self):
        """`extra={RELAXATION: self.name}` — the handler reads the rule from
        that field, so a stamp carrying anything else names the wrong rule."""
        bad = []
        for path in sorted(RULES_DIR.glob('*.py')):
            tree = ast.parse(path.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and node.keywords):
                    continue
                for kw in node.keywords:
                    if kw.arg != 'extra' or not isinstance(kw.value, ast.Dict):
                        continue
                    for k, v in zip(kw.value.keys, kw.value.values):
                        if not (isinstance(k, ast.Name) and k.id == 'RELAXATION'):
                            continue
                        if not (isinstance(v, ast.Attribute)
                                and v.attr == 'name'):
                            bad.append(f'{path.name}:{node.lineno}')
        assert not bad, bad
