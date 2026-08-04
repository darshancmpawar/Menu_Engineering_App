"""
Pytest configuration and shared fixtures
"""

import os
import sys
from pathlib import Path

import pytest

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Seed dummy values for env vars that api.config.validate_required_env()
# insists on at import time. Supabase is replaced by the FakeSupabase
# fixture.
os.environ.setdefault("SUPABASE_URL", "http://fake-supabase.invalid")
os.environ.setdefault("SUPABASE_KEY", "fake-key-for-tests")


@pytest.fixture(scope="session")
def project_root_path():
    """Return the project root path"""
    return Path(__file__).parent.parent


@pytest.fixture(scope="session")
def sample_data_path(project_root_path):
    """Return path to sample data file (the reference/Bangalore ontology)."""
    return project_root_path / "data" / "raw" / "city_items" / "bangalore.xlsx"


@pytest.fixture(scope="session")
def ensure_sample_data_exists(sample_data_path):
    """Ensure sample data file exists before running tests"""
    if not sample_data_path.exists():
        pytest.skip(f"Sample data not found at {sample_data_path}. Run create_sample_data.py first.")
    return sample_data_path


# ---------------------------------------------------------------------------
# Fake Supabase fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def seeded_fake_supabase():
    """Build a FakeSupabase pre-seeded with one usable client + schema.

    Covers the tables read by ClientConfigLoader, HistoryManager and the
    API plan/regenerate paths. History tables start empty.
    """
    from tests.fake_supabase import FakeSupabase

    # Consolidated schema: the whole client config lives in clients.counters
    # (counters[0] is the primary the solver plans from). version=1 mirrors
    # the Supabase schema default returned by /client-config GET.
    fake = FakeSupabase(seed={
        'clients': [
            {
                'name': 'Rippling',
                'version': 1,
                'counters': [
                    {
                        'name': 'Counter 1',
                        'categories': [
                            'welcome_drink', 'starter', 'soup', 'salad',
                            'rice', 'dal', 'veg_gravy', 'veg_dry', 'bread',
                            'curd_side', 'dessert',
                        ],
                        'slot_counts': {},
                        'theme_map': {},
                    },
                ],
            },
        ],
        'app_settings': [],
        'menu_history': [],
        'week_signatures': [],
    })
    return fake


@pytest.fixture
def fake_supabase(monkeypatch, seeded_fake_supabase):
    """Install the fake as the process-wide Supabase client.

    Resets the lazy singletons in ``src.db`` and ``api.app`` so the fake is
    observed by every subsequent call inside the test.
    """
    import src.db as db_mod
    monkeypatch.setattr(db_mod, '_sb_client', seeded_fake_supabase, raising=False)

    try:
        import api.app as api_app
        monkeypatch.setattr(api_app, '_client_loader', None, raising=False)
        # All four are dicts, not None-sentinels — the ontology, non-veg-name
        # and F5 pool caches are keyed by resolved ontology path and the rule
        # cache by city. Resetting a stale name (`_pools`, `_df`,
        # `_nonveg_items`, `_menu_rules`) silently created a junk attribute and
        # left the real caches leaking across tests.
        api_app.reset_caches()
    except ImportError:
        pass

    return seeded_fake_supabase


@pytest.fixture(autouse=True)
def _reset_rate_limit_buckets():
    """Per-principal rate-limit buckets live on module-level singletons, so a
    test ordering that exhausts alice@test.com's /plan bucket would break
    a later test. Reset between tests so every test starts full."""
    try:
        from api.rate_limit import reset_for_tests
    except ImportError:
        yield
        return
    reset_for_tests()
    yield
    reset_for_tests()
