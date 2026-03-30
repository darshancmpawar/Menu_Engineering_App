# Tests Directory

This directory contains all test files for the Ikigai Masala menu planning system.

## Structure

```
tests/
├── __init__.py              # Test package initialization
├── conftest.py              # Pytest configuration and shared fixtures
├── test_preprocessor.py     # Tests for preprocessor module
└── README.md                # This file
```

## Running Tests

### Run all tests
```bash
pytest
```

### Run specific test file
```bash
pytest tests/test_preprocessor.py
```

### Run with verbose output
```bash
pytest -v
```

### Run specific test class
```bash
pytest tests/test_preprocessor.py::TestExcelReader -v
```

### Run specific test method
```bash
pytest tests/test_preprocessor.py::TestExcelReader::test_read_excel_file -v
```

### Run with coverage report (if pytest-cov installed)
```bash
pytest --cov=src --cov-report=html
```

## Test Organization

### test_preprocessor.py

Tests for the preprocessor module (MVP version):

**TestExcelReader** (4 tests)
- `test_read_excel_file`: Verify Excel file reading
- `test_read_nonexistent_file`: Error handling for missing files
- `test_validate_schema_success`: Schema validation with correct columns
- `test_validate_schema_without_reading`: Schema validation error handling

**TestDataCleanser** (5 tests)
- `test_clean_removes_duplicates`: Duplicate removal
- `test_clean_removes_invalid_rows`: Invalid row removal
- `test_clean_standardizes_text`: Text standardization (lowercase, trim)
- `test_clean_handles_missing_values`: Missing value handling
- `test_clean_preserves_valid_data`: Data preservation

**TestDataSerializer** (4 tests)
- `test_serialize_creates_files`: File creation during serialization
- `test_serialize_and_load`: Roundtrip serialization/loading
- `test_load_nonexistent_dataset`: Error handling for missing datasets
- `test_serialize_metadata_content`: Metadata content verification

**TestPreprocessorIntegration** (2 tests)
- `test_full_pipeline`: Complete preprocessing pipeline
- `test_pipeline_with_caching`: Pipeline with caching

## Fixtures

### From conftest.py

- `project_root_path`: Returns project root directory path
- `sample_data_path`: Returns path to sample data file
- `ensure_sample_data_exists`: Ensures sample data exists before tests

### Test-specific fixtures

- `sample_data`: Creates sample DataFrame for testing (DataCleanser tests)
- `sample_dataframe`: Creates sample DataFrame (DataSerializer tests)
- `temp_serializer`: Creates serializer with temporary directory (DataSerializer tests)

## Test Markers

Configure in `pytest.ini`:

- `@pytest.mark.unit`: Unit tests
- `@pytest.mark.integration`: Integration tests
- `@pytest.mark.slow`: Slow running tests

Usage:
```bash
# Run only unit tests
pytest -m unit

# Run only integration tests
pytest -m integration

# Skip slow tests
pytest -m "not slow"
```

## Requirements

- pytest >= 7.0.0
- Sample data must exist: `data/raw/menu_items.xlsx`

To create sample data:
```bash
python3 create_sample_data.py
```

## Best Practices

1. **One test per behavior**: Each test should verify one specific behavior
2. **Clear test names**: Use descriptive names that explain what is being tested
3. **Use fixtures**: Share common setup code via fixtures
4. **Test edge cases**: Include tests for error conditions and edge cases
5. **Keep tests independent**: Tests should not depend on each other
6. **Use assertions wisely**: Each test should have clear, specific assertions

## Adding New Tests

When adding new test files:

1. Name the file `test_*.py`
2. Place in the `tests/` directory
3. Import necessary modules from `src/`
4. Organize tests into classes (TestClassName)
5. Use descriptive test method names (`test_what_it_does`)
6. Add docstrings to explain what each test verifies

Example:
```python
class TestMyNewModule:
    """Tests for MyNewModule"""
    
    def test_basic_functionality(self):
        """Test that basic functionality works"""
        # Arrange
        obj = MyNewModule()
        
        # Act
        result = obj.do_something()
        
        # Assert
        assert result == expected_value
```

## Continuous Integration

These tests are designed to run in CI/CD pipelines. Ensure:
- All dependencies are in `requirements.txt`
- Sample data is generated or available
- Tests complete in reasonable time
- No external dependencies (databases, APIs) in unit tests

## Test Coverage

Current coverage (preprocessor module):
- ✅ ExcelReader: 100%
- ✅ DataCleanser: 100%
- ✅ DataSerializer: 100%
- ✅ Integration: 100%

Total: **15 tests, all passing**
