"""Executable architecture constraints — the dependency direction is one-way.

Layering is the kind of rule that decays silently: one convenient import inside a
function, wrapped in `try/except ImportError` so nothing visibly breaks, and the
direction is reversed. That is exactly how the three violations these tests now
forbid got in:

  * `src/solver/menu_solver.py` did `from api.concurrency import get_worker_count`
    inside its solve loop, so the CP-SAT domain depended on the Flask package;
  * `src/db.py` did `import streamlit` to read `st.secrets`, so the database
    singleton depended on a UI framework;
  * `src/db.py` did a lazy `from api.config import SUPABASE_TIMEOUT_SECONDS`,
    with a comment admitting it was lazy to dodge an import cycle.

All three were papered over with try/except and all three worked, which is why
none of them showed up as a failure. A test is the only thing that catches this
class of drift, so the rule lives here rather than in a document.

The intended direction:

    interfaces  (api/, app.py, ui/, customisation/)
        depends on ->  src/  (solver, rules, preprocessor, client, history)
        depends on ->  src/settings.py, src/constants.py   (leaves)

Nothing in `src/` may point back up.
"""

from __future__ import annotations

import ast
import os
import sys

import pytest

def _repo_root() -> str:
    """Walk up to the directory holding `pytest.ini` and `src/`.

    Anchored on a marker rather than counting `..` levels: this file moved from
    `tests/` to `tests/platform/` and a hard-coded two-levels-up silently made
    SRC point at a directory that does not exist, so `_src_modules()` yielded
    nothing and the 54 layering checks collapsed into one empty parametrisation
    that passed. A guard that can quietly stop guarding is worse than none.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    while True:
        if (os.path.isfile(os.path.join(here, 'pytest.ini'))
                and os.path.isdir(os.path.join(here, 'src'))):
            return here
        parent = os.path.dirname(here)
        if parent == here:
            raise RuntimeError('repo root not found above ' + __file__)
        here = parent


REPO = _repo_root()
SRC = os.path.join(REPO, 'src')
TESTS = os.path.join(REPO, 'tests')

#: Packages that live *above* the domain. `src/` importing any of these is the
#: inversion this file exists to prevent.
INTERFACE_PACKAGES = {'api', 'ui', 'customisation', 'streamlit', 'flask'}


def _src_modules():
    for root, _dirs, files in os.walk(SRC):
        if '__pycache__' in root:
            continue
        for name in files:
            if name.endswith('.py'):
                yield os.path.join(root, name)


def _imported_roots(path):
    """Every top-level package this file imports, including inside functions.

    Walking the whole AST rather than just module-level imports is the point: all
    three historical violations were *function-local* imports, invisible to a
    check that only looked at the top of the file.
    """
    with open(path, encoding='utf-8') as fh:
        tree = ast.parse(fh.read(), filename=path)
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            # level > 0 is a relative import — always within src/, fine.
            if node.level == 0 and node.module:
                roots.add(node.module.split('.')[0])
    return roots


class TestTheDomainNeverImportsAnInterface:
    @pytest.mark.parametrize('path', sorted(_src_modules()),
                             ids=lambda p: os.path.relpath(p, REPO))
    def test_no_upward_import(self, path):
        bad = _imported_roots(path) & INTERFACE_PACKAGES
        assert not bad, (
            f'{os.path.relpath(path, REPO)} imports {sorted(bad)}. Settings the '
            f'domain needs belong in src/settings.py; runtime values the web '
            f'layer owns should be injected (see SolverConfig.'
            f'worker_count_provider), not imported.')

    def test_the_check_would_actually_catch_a_violation(self):
        """Guard against the guard being vacuous — if INTERFACE_PACKAGES or the
        AST walk broke, every test above would pass for the wrong reason."""
        import tempfile
        with tempfile.NamedTemporaryFile('w', suffix='.py', delete=False) as fh:
            fh.write('def f():\n    from api.concurrency import get_worker_count\n')
            tmp = fh.name
        try:
            assert _imported_roots(tmp) & INTERFACE_PACKAGES == {'api'}
        finally:
            os.unlink(tmp)


class TestTheDomainRunsWithoutTheInterfaces:
    """The strongest form of the same rule: `src/` must import even when neither
    the web package nor Streamlit is installed at all."""

    def test_src_imports_with_api_and_streamlit_blocked(self):
        blocked = {'api', 'streamlit'}

        class _Blocker:
            def find_module(self, name, path=None):
                return self if name.split('.')[0] in blocked else None

            def load_module(self, name):
                raise ImportError(f'blocked for test: {name}')

        # Drop anything already imported so the blocker is actually consulted.
        saved = {k: v for k, v in sys.modules.items()
                 if k.split('.')[0] in blocked | {'src'}}
        for key in list(saved):
            del sys.modules[key]
        sys.meta_path.insert(0, _Blocker())
        try:
            import importlib
            for mod in ('src.settings', 'src.db', 'src.constants',
                        'src.solver.menu_solver',
                        'src.menu_rules.menu_rule_loader',
                        'src.preprocessor.pool_builder'):
                importlib.import_module(mod)
        finally:
            sys.meta_path.pop(0)
            sys.modules.update(saved)


class TestSettingsIsTheSharedLeaf:
    def test_settings_imports_nothing_of_ours(self):
        """`src/settings.py` is the bottom of the graph. If it grows an import of
        api/ or even another src/ module, it stops being safe for everything to
        depend on."""
        roots = _imported_roots(os.path.join(SRC, 'settings.py'))
        assert not (roots & INTERFACE_PACKAGES)
        assert 'src' not in roots

    def test_api_config_reexports_rather_than_redefining(self):
        """One source of truth for the Supabase timeout. Two `os.getenv` calls
        with the same default in two files drift the moment one changes."""
        from api.config import SUPABASE_TIMEOUT_SECONDS as via_api
        from src.settings import SUPABASE_TIMEOUT_SECONDS as via_src
        assert via_api is via_src

    def test_credentials_come_from_the_environment(self, monkeypatch):
        from src.settings import resolve_supabase_credentials
        monkeypatch.setenv('SUPABASE_URL', 'https://example.supabase.co')
        monkeypatch.setenv('SUPABASE_KEY', 'k')
        assert resolve_supabase_credentials() == (
            'https://example.supabase.co', 'k')

    def test_missing_credentials_fail_loudly(self, monkeypatch):
        """Rather than building a client that 401s on every later call."""
        from src.settings import resolve_supabase_credentials
        monkeypatch.delenv('SUPABASE_URL', raising=False)
        monkeypatch.delenv('SUPABASE_KEY', raising=False)
        with pytest.raises(KeyError):
            resolve_supabase_credentials()


class TestWorkerCountIsInjectedNotImported:
    def test_solver_default_is_standalone(self):
        """No provider → the solver still runs, with a fixed worker count. This
        is what the old `except ImportError: = 8` branch was for."""
        from src.solver.menu_solver import SolverConfig
        assert SolverConfig().worker_count_provider is None

    def test_provider_is_called_per_solve_not_captured_once(self):
        """A callable, not an int, so the API's dynamic scaling still applies on
        every restart attempt — capturing a number at config-build time would
        silently drop that."""
        from src.solver.menu_solver import SolverConfig
        calls = []

        def provider():
            calls.append(1)
            return 3

        cfg = SolverConfig(deterministic=False, worker_count_provider=provider)
        assert cfg.worker_count_provider() == 3
        assert len(calls) == 1

    def test_the_api_passes_the_real_provider(self):
        from api.concurrency import get_worker_count
        import api.app as api_app
        import inspect
        src = inspect.getsource(api_app._build_solver_config)
        assert 'worker_count_provider=get_worker_count' in src
        assert callable(get_worker_count)

class TestOntologyCachesAreNotPokedByName:
    """The ontology caches moved into `src/ontology/repository.py` and are reset
    with `api_app.reset_caches()`.

    This test exists because the failure mode of regressing it is silent. If a
    test sets `api_app._menu_data_by_path = {}` today, that just creates an
    unused attribute — nothing reads it — so the test still passes while sharing
    a cache with every other test in the session. A stale 4,300-row Bangalore
    frame would then answer a Chennai assertion, and the failure would surface in
    a different file depending on test order.
    """

    RETIRED = ('_menu_data_by_path', '_nonveg_items_by_path',
               '_menu_rules_by_city', '_filtered_cache')

    def test_no_test_file_references_a_retired_cache_global(self):
        import glob
        offenders = {}
        here = os.path.abspath(__file__)
        # Recursive: the suite is split into tests/clients, cities, rules,
        # data, ui and platform, so a flat glob of this file's own directory
        # would check six files and miss seventy.
        for path in sorted(glob.glob(os.path.join(TESTS, '**', '*.py'),
                                     recursive=True)):
            # This file necessarily spells the retired names out — it is the one
            # explaining them.
            if os.path.abspath(path) == here:
                continue
            with open(path, encoding='utf-8') as fh:
                body = fh.read()
            # `api_app._filtered_cache` etc. — a bare mention in a test NAME or a
            # docstring is harmless, so require the attribute-access form.
            hits = [n for n in self.RETIRED if f'.{n}' in body]
            if hits:
                offenders[os.path.basename(path)] = hits
        assert not offenders, (
            f'{offenders} — use api_app.reset_caches() instead; setting the old '
            f'globals silently does nothing and loses test isolation.')

    def test_reset_caches_actually_empties_them(self):
        import api.app as api_app
        api_app._get_menu_data('Chennai')
        assert api_app._ontology.cache_sizes()['menu_data'] > 0
        api_app.reset_caches()
        assert all(v == 0 for v in api_app._ontology.cache_sizes().values())

    def test_cities_sharing_a_workbook_share_one_entry(self):
        """Why the caches are keyed by resolved path, not city name: a city with
        no workbook falls back to Bangalore's list, and keying by city would hold
        two copies of a 6,000-row frame.

        NCR, Chennai and Hyderabad have each been the example here and each got
        its own file, so the sharing side is now a city the app has never heard
        of — which is the same state every one of them was in first. Both
        directions still assert: a distinct file is a distinct entry, a shared
        file is not."""
        import api.app as api_app
        api_app.reset_caches()
        api_app._get_menu_data('Bangalore')
        api_app._get_menu_data('Kolkata')        # no file — shares bangalore.xlsx
        assert api_app._ontology.cache_sizes()['menu_data'] == 1
        api_app._get_menu_data('NCR')            # own file
        assert api_app._ontology.cache_sizes()['menu_data'] == 2
        api_app._get_menu_data('Chennai')        # own file
        assert api_app._ontology.cache_sizes()['menu_data'] == 3
        api_app._get_menu_data('Hyderabad')      # own file, seeded from Bangalore
        assert api_app._ontology.cache_sizes()['menu_data'] == 4
        api_app.reset_caches()


class TestOperatorFacingLogsKeepOneName:
    """Moving code must not change where a warning appears to come from.

    `_validate_constant_values` logged under `api.app` until it moved to
    `src/application/constant_items.py`, at which point the same warning started
    arriving as `src.application.constant_items`. Log records are observable
    output: anything filtering or alerting on `api.app` silently stopped matching.
    """

    def test_moved_warnings_still_emit_under_the_stable_name(self):
        from src.application import constant_items
        from src.log_names import APP_LOGGER_NAME
        assert constant_items.logger.name == APP_LOGGER_NAME

    def test_the_stable_name_is_the_one_already_deployed(self):
        """Changing this string breaks somebody's alerting — pinned so that is a
        deliberate act with a failing test, not a side effect of a refactor."""
        from src.log_names import APP_LOGGER_NAME
        assert APP_LOGGER_NAME == 'api.app'

    def test_pinning_a_name_is_not_an_upward_import(self):
        """It is a string, not a dependency: src/log_names.py must stay a leaf."""
        roots = _imported_roots(os.path.join(SRC, 'log_names.py'))
        assert not (roots & INTERFACE_PACKAGES)
        assert 'src' not in roots


class TestWeekdaySpellingsAgreeAcrossModules:
    """A config writing "sat" must mean the same thing to every rule that
    reads a weekday.

    Two tables hold the accepted spellings and they cannot be merged, because
    they map to different things: `menu_solver._WEEKDAY_ALIASES` resolves an
    alias to a full weekday NAME (what `working_days` and
    `slot_day_restriction` compare against), and
    `selector_frequency_rule._WEEKDAY_TOKENS` resolves it to a weekday INDEX
    (what `forbidden_weekdays` needs for `date.weekday()`).

    What must not happen is the two drifting: adding "thurs" to one leaves a
    config that works in `slot_day_restriction` and is silently ignored in
    `forbidden_weekdays` — a weekday ban that reads as configured and bans
    nothing. Pinned as an agreement on the KEYS, which is the only thing they
    share and the only thing that can go wrong.
    """

    def _tables(self):
        from src.menu_rules.selector_frequency_rule import _WEEKDAY_TOKENS
        from src.solver.menu_solver import _WEEKDAY_ALIASES
        return _WEEKDAY_TOKENS, _WEEKDAY_ALIASES

    def test_they_accept_the_same_spellings(self):
        tokens, aliases = self._tables()
        assert set(tokens) == set(aliases)

    def test_every_weekday_has_a_short_and_a_long_spelling(self):
        tokens, _ = self._tables()
        assert len(tokens) == 14, sorted(tokens)
        assert set(tokens.values()) == set(range(7))

    def test_the_two_resolve_an_alias_consistently(self):
        """Different value types, same answer: alias -> index and alias -> name
        must name the same day."""
        import datetime as dt
        tokens, aliases = self._tables()
        # 2026-09-07 is a Monday, so index i is that weekday's name.
        monday = dt.date(2026, 9, 7)
        for alias, idx in tokens.items():
            expected = (monday + dt.timedelta(days=idx)).strftime('%A').lower()
            assert aliases[alias] == expected, (alias, idx, aliases[alias])


class TestTheExplainLayerStaysOffline:
    """`src/explain/` computes the verdicts an explanation may assert, and it
    must not be able to reach the network.

    That is not tidiness. The design of the feature is that Python decides
    every claim and a model only phrases it, with a validator rejecting any
    number or dish name that did not come from the pack
    (`api/explain_llm.py`). If a verdict module could call out on its own, the
    boundary that makes confabulation structurally impossible would have a hole
    in it — and the verdicts would stop being unit-testable offline, which is
    what lets `tests/explain/` run in a second with no solver or database.

    `INTERFACE_PACKAGES` above does not cover this: `requests` is not an
    interface package, it is a client. So it is checked separately, and only
    for the subtree whose whole contract is being pure.
    """

    #: Anything that can open a socket or talk to a model provider.
    NETWORK_PACKAGES = {
        'requests', 'httpx', 'urllib', 'urllib2', 'urllib3', 'http',
        'socket', 'aiohttp', 'openai', 'anthropic', 'google', 'genai',
        'google_generativeai', 'vertexai', 'boto3', 'litellm',
    }

    def _explain_modules(self):
        base = os.path.join(SRC, 'explain')
        if not os.path.isdir(base):
            return []
        return [os.path.join(base, f) for f in sorted(os.listdir(base))
                if f.endswith('.py')]

    def test_the_package_exists(self):
        """Otherwise every assertion below passes over an empty list."""
        assert self._explain_modules(), 'src/explain/ is missing'

    def test_no_explain_module_imports_a_network_client(self):
        offenders = []
        for path in self._explain_modules():
            roots = _imported_roots(path)
            hit = roots & self.NETWORK_PACKAGES
            if hit:
                offenders.append(f'{os.path.basename(path)} imports {sorted(hit)}')
        assert not offenders, '; '.join(offenders)

    def test_no_explain_module_imports_an_interface(self):
        offenders = []
        for path in self._explain_modules():
            hit = _imported_roots(path) & INTERFACE_PACKAGES
            if hit:
                offenders.append(f'{os.path.basename(path)} imports {sorted(hit)}')
        assert not offenders, '; '.join(offenders)

    def test_the_prose_layer_is_the_one_allowed_to_reach_out(self):
        """The other half — `api/explain_llm.py` SHOULD be able to, and lives
        in `api/` precisely so that it can. If it ever moves under `src/`, the
        checks above would start failing, which is the intended alarm."""
        path = os.path.join(REPO, 'api', 'explain_llm.py')
        if not os.path.isfile(path):
            pytest.skip('the prose layer has not been added yet')
        assert 'src.explain' in open(path, encoding='utf-8').read()
