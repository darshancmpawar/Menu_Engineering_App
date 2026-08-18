"""Fast tests for AttributeGroupingRule (Phase-3, rulebook 79 + 82).

End-to-end CP-SAT behavior (dal-colour alternation, sambar key-ingredient
cap) is asserted on real data in the slow integration suite.
"""

from src.menu_rules import MenuRuleLoader
from src.menu_rules.attribute_grouping_rule import AttributeGroupingRule
from src.menu_rules.base_menu_rule import MenuRuleType


class TestConfig:
    def test_loader_registers_type(self):
        r = MenuRuleLoader()._create_rule({
            'type': 'attribute_grouping', 'name': 'x',
            'base_slot': 'dal', 'group_by': 'item_color', 'non_consecutive': True,
        })
        assert isinstance(r, AttributeGroupingRule)
        assert r.rule_type == MenuRuleType.ATTRIBUTE_GROUPING
        assert r.group_by == 'item_color' and r.base_slot == 'dal'
        assert r.non_consecutive and r.max_per_group is None

    def test_max_per_group_parsed(self):
        r = AttributeGroupingRule({
            'name': 'x', 'base_slot': 'sambar',
            'group_by': 'key_ingredient', 'max_per_group': 1})
        assert r.validate_config()
        assert r.max_per_group == 1 and not r.non_consecutive

    def test_requires_group_by(self):
        r = AttributeGroupingRule({'name': 'x', 'non_consecutive': True})
        assert not r.validate_config()
        assert any('group_by' in e for e in r.validation_errors())

    def test_requires_a_constraint(self):
        r = AttributeGroupingRule({'name': 'x', 'group_by': 'item_color'})
        assert not r.validate_config()
        assert any('non_consecutive' in e and 'max_per_group' in e
                   for e in r.validation_errors())

    def test_negative_max_rejected(self):
        r = AttributeGroupingRule({
            'name': 'x', 'group_by': 'item_color', 'max_per_group': -1})
        assert not r.validate_config()

    def test_both_constraints_valid(self):
        r = AttributeGroupingRule({
            'name': 'x', 'base_slot': 'dal', 'group_by': 'item_color',
            'non_consecutive': True, 'max_per_group': 2})
        assert r.validate_config()


class TestApplyIsSafeWithoutContext:
    def test_apply_no_context_is_noop(self):
        # No cells / link_any in context → the rule must return without error
        # (mirrors how selector_frequency degrades in non-solve contexts).
        r = AttributeGroupingRule({
            'name': 'x', 'base_slot': 'dal', 'group_by': 'item_color',
            'non_consecutive': True})
        r.apply(model=None, variables={}, menu_data=None, context={})
