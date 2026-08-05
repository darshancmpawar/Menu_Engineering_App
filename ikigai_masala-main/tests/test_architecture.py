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

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, 'src')

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
        for path in sorted(glob.glob(os.path.join(
                os.path.dirname(here), '*.py'))):
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
        """Why the caches are keyed by resolved path, not city name: Hyderabad
        falls back to Bangalore's list, and keying by city would hold two copies
        of a 4,300-row frame. (NCR used to share it too; it now has its own
        file, so it is a second entry — which is exactly the path-keying working:
        a distinct file is a distinct entry, a shared file is not.)"""
        import api.app as api_app
        api_app.reset_caches()
        api_app._get_menu_data('Bangalore')
        api_app._get_menu_data('Hyderabad')      # shares bangalore.xlsx
        assert api_app._ontology.cache_sizes()['menu_data'] == 1
        api_app._get_menu_data('NCR')            # own file now
        assert api_app._ontology.cache_sizes()['menu_data'] == 2
        api_app._get_menu_data('Chennai')        # own file
        assert api_app._ontology.cache_sizes()['menu_data'] == 3
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
