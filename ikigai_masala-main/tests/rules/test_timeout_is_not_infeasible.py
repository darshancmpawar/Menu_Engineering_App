""""No plan" has two causes and they need different words.

CP-SAT answers INFEASIBLE when the constraints genuinely cannot be met, and
UNKNOWN when it ran out of time before proving it either way. `_configure_and_solve`
already separates them; the outer error in `MenuSolver.solve` used to flatten
both into "the rules configured for this counter cannot all be satisfied over
the requested horizon".

That sentence asserts a configuration conflict. Said about a timeout it is
simply false, and it costs real time: it sends an operator hunting for a rule
contradiction that does not exist when the fix is a longer `time_limit`.

Measured on the 25-day rolling sweep, which is what turned this up: seven
counters "failed", and four of them replanned cleanly on a quiet machine at the
same settings. They were timeouts wearing the impossibility message.
"""

from __future__ import annotations

import pytest

from src.solver.menu_solver import (
    INFEASIBLE_MESSAGE, MAX_FRESHNESS_BONUS, MenuSolver, TIMEOUT_MESSAGE,
)


class TestTheTwoOutcomesSayDifferentThings:
    def test_they_are_not_the_same_message(self):
        assert INFEASIBLE_MESSAGE != TIMEOUT_MESSAGE

    def test_the_timeout_message_does_not_blame_the_rules(self):
        """The specific falsehood this fixes."""
        assert "cannot all be satisfied" not in TIMEOUT_MESSAGE
        assert "may still be satisfiable" in TIMEOUT_MESSAGE

    def test_the_timeout_message_names_the_remedy(self):
        assert "longer time_limit" in TIMEOUT_MESSAGE

    def test_the_infeasible_message_still_blames_the_rules(self):
        """The other half — a real contradiction must still say so plainly, or
        the fix trades one wrong message for another."""
        assert "cannot all be satisfied over the requested horizon" in INFEASIBLE_MESSAGE
        assert "time limit" not in INFEASIBLE_MESSAGE.lower()


class TestTheSolverPicksBetweenThem:
    def test_solve_selects_on_the_inner_status(self):
        """The inner attempt raises '(TIME LIMIT)' or '(INFEASIBLE)'; the outer
        handler must read that rather than assume."""
        import inspect
        src = inspect.getsource(MenuSolver.solve)
        assert "TIME LIMIT" in src
        assert "TIMEOUT_MESSAGE" in src and "INFEASIBLE_MESSAGE" in src

    def test_the_inner_statuses_are_still_distinguished(self):
        """The premise. If `_configure_and_solve` stops separating them the
        outer choice silently becomes a coin flip."""
        import inspect
        src = inspect.getsource(MenuSolver._configure_and_solve)
        assert "INFEASIBLE" in src and "TIME LIMIT" in src

    def test_both_paths_keep_the_tightest_slot_detail(self):
        """`detail` names the slot closest to starving, which is the actionable
        half either way — it belonged on the impossibility path only."""
        import inspect
        src = inspect.getsource(MenuSolver.solve)
        assert "head + detail" in src.replace("\n", " ")


class TestTheMessagesReachTheCaller:
    @pytest.mark.parametrize("message", [INFEASIBLE_MESSAGE, TIMEOUT_MESSAGE])
    def test_a_message_is_a_sentence_not_a_status_code(self, message):
        """Both are shown to an operator in the API's 500 body, so they have to
        read as English rather than as `UNKNOWN`."""
        assert message.endswith(".")
        assert len(message.split()) > 8
        assert message[0].isupper()
