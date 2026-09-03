"""Two solves must never share a rule instance.

Rules are not stateless. `UniqueItemsMenuRule.apply()` stores the model's
repeat-penalty VARIABLES on `self`, and `get_objective_terms()` reads them back
a moment later — so the instance carries one solve's model between two calls.

`OntologyRepository.rules_for_city` caches one ruleset per city for the whole
process, and `@solver_gate` runs two solves at once by design (1 active -> 9
CP-SAT workers, 2 active -> 5 each). A client with no overrides used to get that
cached list back unchanged, so any two clients of one city solving concurrently
shared every rule object. The second `apply()` then overwrites the first's
variable list and the first solve's objective references variables belonging to
the OTHER model. What happens next depends on the two models' relative size and
is measured in `TestTheStateThatMadeItMatter`: sometimes a 500, more often a
menu that solved OPTIMAL against the wrong variables with nothing logged.

It is invisible to every single-solve test, which is why it survived: the state
is written and read inside one call, and interleaving is the only thing that
separates them. So the tests here are about object identity, plus one that
actually interleaves two model builds.
"""

from __future__ import annotations

from ortools.sat.python import cp_model

from src.menu_rules.menu_rule_loader import MenuRuleLoader
from src.menu_rules.unique_items_menu_rule import UniqueItemsMenuRule


def _ruleset():
    return MenuRuleLoader().load_for_city('bangalore')


class TestTheCachedRulesetIsNeverHandedOut:
    def test_a_client_with_no_overrides_gets_fresh_instances(self):
        """The path that was sharing. `__no_such_client__` has no block, which
        is the same situation as most of the fleet."""
        base = _ruleset()
        got = MenuRuleLoader().load_for_client('__no_such_client__', base)
        assert len(got) == len(base)
        shared = [a for a, b in zip(base, got) if a is b]
        assert not shared, [getattr(r, 'name', '?') for r in shared]

    def test_two_clients_share_nothing_with_each_other(self):
        base = _ruleset()
        a = MenuRuleLoader().load_for_client('__client_a__', base)
        b = MenuRuleLoader().load_for_client('__client_b__', base)
        assert not ({id(r) for r in a} & {id(r) for r in b})

    def test_the_rules_survive_the_rebuild(self):
        """A rebuild that quietly dropped a rule would trade a rare 500 for a
        menu that ignores a constraint on every request — much worse."""
        base = _ruleset()
        got = MenuRuleLoader().load_for_client('__no_such_client__', base)
        assert ([getattr(r, 'name', None) for r in base]
                == [getattr(r, 'name', None) for r in got])

    def test_a_stub_without_a_config_is_passed_through(self):
        """Tests pass rule stubs with no `config`; there is nothing to rebuild
        from, and dropping them would break those callers."""
        class _Stub:
            config = None
            name = 'stub'
        stub = _Stub()
        got = MenuRuleLoader().load_for_client('__no_such_client__', [stub])
        assert got == [stub]


class TestTheStateThatMadeItMatter:
    """What sharing actually costs, measured rather than assumed.

    A CP-SAT expression carries variable INDICES, not objects, so a foreign
    variable is not detected as foreign — it is resolved against whichever model
    is being solved. That splits the damage in two, and the quiet half is the
    worse one:

      * the other model is BIGGER — an index runs past this model's variable
        list and CP-SAT answers MODEL_INVALID. The request 500s. Visible.
      * the other model is the same size or smaller — every index resolves, to
        the WRONG variables. The solve returns OPTIMAL and the menu is served,
        having optimised something that has nothing to do with it. Nothing is
        logged and nothing is red.

    So "it 500s under concurrency" understates it: most of the time it does not.
    """

    def _cells_ctx(self, model, days=3, dishes=2):
        """A STARVED slot — more days than distinct dishes.

        Starved on purpose. `apply()` only records penalty variables when a slot
        cannot be unique (`starved_slots`); on the fast path the list stays
        empty and there is nothing to corrupt, so a comfortable pool would make
        the reproductions below pass without reproducing anything.
        """
        import datetime as dt
        import pandas as pd
        from src.solver.menu_solver import _Cell

        names = [f'dish_{i}' for i in range(dishes)]
        cells, item_to_vars = [], {d: [] for d in names}
        for day in range(days):
            rows = [pd.Series({'item': d, 'course_type': 'veg_gravy'})
                    for d in names]
            cell = _Cell(day, dt.date(2026, 9, 7) + dt.timedelta(days=day),
                         'veg_gravy__1', 'veg_gravy',
                         pd.DataFrame(rows), [False] * dishes)
            cell.cand_rows = rows
            cell.x_vars = [model.NewBoolVar(f'd{day}_{d}') for d in names]
            for d, v in zip(names, cell.x_vars):
                item_to_vars[d].append(v)
            cells.append(cell)
        return {'cells': cells, 'item_to_vars': item_to_vars}

    def _interleave(self, a, b):
        """Build two models through ONE rule, the way two requests interleave.
        Returns the first model and the objective terms it is handed."""
        rule = UniqueItemsMenuRule({'name': 'u', 'type': 'unique_items'})
        m1, m2 = cp_model.CpModel(), cp_model.CpModel()
        c1, c2 = self._cells_ctx(m1, *a), self._cells_ctx(m2, *b)
        rule.apply(m1, {}, None, c1)
        rule.apply(m2, {}, None, c2)   # request B clobbers request A's state
        terms = rule.get_objective_terms(m1, c1)
        assert terms, 'the fixture stopped being starved — nothing to corrupt'
        return m1, terms

    def test_apply_writes_model_state_onto_the_instance(self):
        """The premise. If this stops being true the sharing above stops being
        a bug, and this file should be re-read rather than deleted."""
        rule = UniqueItemsMenuRule({'name': 'u', 'type': 'unique_items'})
        model = cp_model.CpModel()
        rule.apply(model, {}, None, self._cells_ctx(model))
        assert hasattr(rule, '_repeat_penalty_vars')

    def test_a_bigger_neighbour_makes_the_model_invalid(self):
        """The visible half — this is the reported 500."""
        m1, terms = self._interleave((3, 2), (20, 5))
        m1.Minimize(sum(terms))
        assert cp_model.CpSolver().Solve(m1) == cp_model.MODEL_INVALID

    def test_a_same_sized_neighbour_corrupts_the_objective_silently(self):
        """The half that is worse. Nothing raises, nothing logs, and a menu
        optimised against another client's variables is served as if correct."""
        m1, terms = self._interleave((3, 2), (3, 2))
        m1.Minimize(sum(terms))
        assert cp_model.CpSolver().Solve(m1) == cp_model.OPTIMAL

    def test_a_smaller_neighbour_corrupts_it_silently_too(self):
        """Different horizons are the realistic case — two clients rarely plan
        the same number of days — and it still resolves rather than failing."""
        m1, terms = self._interleave((6, 2), (3, 2))
        m1.Minimize(sum(terms))
        assert cp_model.CpSolver().Solve(m1) == cp_model.OPTIMAL
