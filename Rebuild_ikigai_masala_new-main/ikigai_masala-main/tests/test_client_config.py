"""Tests for ClientConfigLoader."""

import json
import tempfile
import pytest
from pathlib import Path
from src.client.client_config import ClientConfigLoader


@pytest.fixture
def config_path():
    return str(Path(__file__).parent.parent / 'data' / 'configs' / 'clients.json')


class TestClientConfigLoader:
    def test_load(self, config_path):
        loader = ClientConfigLoader(config_path)
        assert len(loader.client_names) == 18

    def test_get_client_rippling(self, config_path):
        loader = ClientConfigLoader(config_path)
        cfg = loader.get_client('Rippling')
        assert cfg.name == 'Rippling'
        assert cfg.menu_category == 'menu_cat_4'
        # Rippling has veg_dry: 2, so should have veg_dry__1 and veg_dry__2
        assert 'veg_dry__1' in cfg.active_slots
        assert 'veg_dry__2' in cfg.active_slots
        assert 'veg_dry' not in cfg.active_slots

    def test_get_client_stripe(self, config_path):
        loader = ClientConfigLoader(config_path)
        cfg = loader.get_client('Stripe')
        assert 'nonveg_main__1' in cfg.active_slots
        assert 'nonveg_main__2' in cfg.active_slots

    def test_get_client_vector_no_overrides(self, config_path):
        loader = ClientConfigLoader(config_path)
        cfg = loader.get_client('Vector')
        # No overrides, so veg_dry should be single
        assert 'veg_dry' in cfg.active_slots

    def test_unknown_client_raises(self, config_path):
        loader = ClientConfigLoader(config_path)
        with pytest.raises(ValueError, match="Unknown client"):
            loader.get_client('NonExistent')

    def test_slot_counts(self, config_path):
        loader = ClientConfigLoader(config_path)
        counts = loader.get_slot_counts_for_client('Rippling')
        assert counts['veg_dry'] == 2
        assert counts['rice'] == 1

    def test_validate(self, config_path):
        loader = ClientConfigLoader(config_path)
        loader.validate()  # Should not raise

    def test_validate_duplicate_names(self, tmp_path):
        cfg = {
            "clients": [
                {"name": "A", "menu_category": "cat1"},
                {"name": "A", "menu_category": "cat1"},
            ],
            "menu_categories": {"cat1": ["bread"]},
            "slot_count_overrides": {},
            "core_min_one_slots": [],
            "constant_slots": [],
            "fallback_menu_category": "cat1",
        }
        p = tmp_path / 'clients.json'
        p.write_text(json.dumps(cfg))
        loader = ClientConfigLoader(str(p))
        with pytest.raises(ValueError, match="Duplicate"):
            loader.validate()

    def test_menu_categories_property(self, config_path):
        loader = ClientConfigLoader(config_path)
        cats = loader.menu_categories
        assert 'menu_cat_1' in cats
        assert isinstance(cats['menu_cat_1'], list)
