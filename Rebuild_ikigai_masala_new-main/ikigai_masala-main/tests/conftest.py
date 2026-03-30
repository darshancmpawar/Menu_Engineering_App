"""
Pytest configuration and shared fixtures
"""

import pytest
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@pytest.fixture(scope="session")
def project_root_path():
    """Return the project root path"""
    return Path(__file__).parent.parent


@pytest.fixture(scope="session")
def sample_data_path(project_root_path):
    """Return path to sample data file"""
    return project_root_path / "data" / "raw" / "menu_items.xlsx"


@pytest.fixture(scope="session")
def ensure_sample_data_exists(sample_data_path):
    """Ensure sample data file exists before running tests"""
    if not sample_data_path.exists():
        pytest.skip(f"Sample data not found at {sample_data_path}. Run create_sample_data.py first.")
    return sample_data_path
