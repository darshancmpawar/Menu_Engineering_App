# Tests

## Running Tests

```bash
# All tests
pytest

# Verbose
pytest -v

# Specific file
pytest tests/test_api.py

# By marker
pytest -m unit
pytest -m integration
pytest -m "not slow"

# With coverage
pytest --cov=src --cov-report=html
```

## Test Files

| File | Module Tested |
|------|--------------|
| `test_api.py` | Flask API endpoints |
| `test_client_config.py` | Supabase-backed client configuration |
| `test_column_mapper.py` | Column mapping and normalization utilities |
| `test_formatters.py` | UI formatting functions (theme labels, slot names, item display) |
| `test_helpers.py` | Solver helper utilities (weekday_type, strip_color_suffix) |
| `test_history_manager.py` | History persistence, cooldown, and signature logic |
| `test_menu_rule_loader.py` | Menu rule factory pattern |
| `test_menu_rules.py` | All 19 constraint rule implementations |
| `test_pool_builder.py` | Per-slot item pool construction |
| `test_prefilter_integration.py` | Integration tests for pool pre-filtering |
| `test_rule_constraints.py` | Constraint application and validation |
| `test_solution_formatter.py` | Solution formatting output (dict, CSV, Excel) |
| `test_theme_filter.py` | Theme-based static pool filtering |

## Fixtures

Defined in `conftest.py`:

- `project_root_path` -- Project root directory
- `sample_data_path` -- Path to sample Excel data
- `ensure_sample_data_exists` -- Ensures test data is available

## Markers

Configured in `pytest.ini`:

- `@pytest.mark.unit` -- Unit tests
- `@pytest.mark.integration` -- Integration tests
- `@pytest.mark.slow` -- Slow tests (solver, full pipeline)

## Requirements

- `pytest >= 7.0.0`
- `pytest-cov >= 4.0.0`
- `data/raw/menu_items.xlsx` must exist for integration tests
