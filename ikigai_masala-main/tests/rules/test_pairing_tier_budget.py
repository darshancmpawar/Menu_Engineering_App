"""Every pairing term together must stay far below one MEDIUM unit.

A pairing is a `low`-tier preference and the tiers are only lexicographic while
everything below a tier, summed, stays under one unit of it (see
`test_objective_tier_headroom.py`, which measures that the THEME tier is already
inverted at `MAX_NUM_DAYS`). Pairings are the first feature to add low-tier mass
deliberately and at scale — one term per rule per day — so the question "how
much mass did we just add" has to be answered by measurement, not by arithmetic
over coefficients.

The budget is **1e8, a tenth of one medium unit**. It is a [proposal] from the
work order, not a derived constant: the honest claim is that a pairing must not
be able to outbid a rulebook rule, and a tenth of a unit is a margin wide enough
that the next few pairings cannot close it either.

Method is `test_objective_tier_headroom`'s, including its hardest-won lesson:
**ask CP-SAT, do not compute**. Summing the gap coefficients looks obviously
right here — the gap vars are independent bools, one per day — but that file
records two arithmetic bounds that looked obviously right and disagreed with
each other by a factor of ten on the same model. So the model is re-solved with
only the pairing terms as its objective and every original constraint intact,
and `BestObjectiveBound()` is read: a valid upper bound on a maximisation even
when the solve times out.

**An UNKNOWN is not a pass.** A probe that ran out of budget returns a bound of
0, which reads as "no mass at all" and would turn a timeout into a clean bill of
health — the exact vacuous-pass this guard's sibling was rewritten to prevent.
"""

from __future__ import annotations

import os

import pytest

from api.config import MAX_NUM_DAYS
from src.constants import OBJECTIVE_TIER_WEIGHTS
from tests.client_fixtures import APP_SETTINGS, CLIENTS
from tests.fake_supabase import FakeSupabase

# The fleet's widest counter, for the same reason the headroom file uses it:
# the budget is only meaningful for the worst case that actually exists.
WIDEST_CLIENT = 'Booking.com'
WIDEST_COUNTER = 0
MONDAY = '2026-08-03'

#: A tenth of one MEDIUM unit. [proposal] — see the module docstring.
PAIRING_BUDGET = 100_000_000

#: Seconds CP-SAT gets to decide. The sibling file measured 20s as far too
#: short on an idle machine (all rungs UNKNOWN) and 240 as enough; this model
#: carries the same constraints plus six small rules, so it inherits 240.
PROBE_SECONDS = int(os.getenv('PAIRING_BUDGET_PROBE_SECONDS', '240'))


def _pairing_rule_configs():
    """The catalogue, from the one place it is written down.

    `scripts/pairing_opportunity.py` already holds every pair's selectors and —
    critically — the CORRECTED `base_slot_b` for the combo categories (phase 1:
    a counter whose sambar shares a cell with dal keys it `dal_sambar`, and the
    obvious `"sambar"` is inert on exactly the counters where the pair has a
    gradient). Reading them from there means the budget is measured against the
    rules that would actually ship, and the two cannot drift apart.
    """
    from scripts.pairing_opportunity import PAIRS, PREFERRED

    out = []
    for pid, spec in PAIRS.items():
        out.append({
            'name': f'pair_{pid.lower()}_budget_probe',
            'type': 'soft_preference',
            'mode': 'prefer_with',
            'priority': 'low',
            'selector_a': spec['sel_a'], 'base_slot_a': spec['slots_a'],
            'selector_b': spec['sel_b'], 'base_slot_b': spec['slots_b'],
            # The SHIPPED weight, not the tier default. This probe first built
            # every rule at 1e6 while P1 and P2 ship at 3e6, so it measured a
            # configuration that does not exist and under-reported the mass.
            'weight': spec.get('weight', PREFERRED),
        })
    return out


@pytest.fixture
def live_clients(monkeypatch):
    import src.db as db_mod
    monkeypatch.setattr(db_mod, '_sb_client', FakeSupabase(seed={
        'clients': [dict(c) for c in CLIENTS],
        'app_settings': [dict(s) for s in APP_SETTINGS],
        'menu_history': [], 'week_signatures': [],
    }), raising=False)
    import api.app as api_app
    monkeypatch.setattr(api_app, '_client_loader', None, raising=False)
    api_app.reset_caches()
    api_app.app.config['TESTING'] = True
    return api_app


@pytest.fixture
def model_with_pairings(live_clients, monkeypatch):
    """The real 30-day model for the widest counter, with every pairing added.

    The rules are appended to what the loader returns rather than written into
    a city ruleset, so this measures the budget BEFORE any of them ships — the
    order the work order asks for (guard first, then rules one at a time).
    """
    from src.menu_rules.soft_preference_rule import SoftPreferenceRule
    import src.application.solve_inputs as si
    from src.solver.menu_solver import MenuSolver

    rules = []
    for cfg in _pairing_rule_configs():
        rule = SoftPreferenceRule(cfg)
        assert rule.validate_config(), (cfg['name'], rule.validation_errors())
        rules.append(rule)

    original_rules_for = si.rules_and_skip_for_client

    def _with_pairings(*a, **kw):
        got = original_rules_for(*a, **kw)
        return (list(got[0]) + rules,) + tuple(got[1:])

    monkeypatch.setattr(si, 'rules_and_skip_for_client', _with_pairings)

    captured: list = []
    original_objective = MenuSolver._build_objective

    def _spy(self, model, cells, rng, similarity, context):
        original_objective(self, model, cells, rng, similarity, context)
        try:
            proto = model.Proto()
            snapshot = type(proto)()
            snapshot.copy_from(proto)
            captured.append({'proto': snapshot, 'cells': len(cells)})
        except Exception:                        # pragma: no cover - defensive
            return

    monkeypatch.setattr(MenuSolver, '_build_objective', _spy)

    with live_clients.app.test_client() as c:
        c.post('/api/v1/plan', json={
            'client_name': WIDEST_CLIENT, 'counter_index': WIDEST_COUNTER,
            'start_date': MONDAY, 'num_days': MAX_NUM_DAYS,
            'time_limit_seconds': 1,
        })
    if not captured:
        pytest.skip('the solver never reached _build_objective for this config')
    return max(captured, key=lambda c: len(c['proto'].objective.vars))


def _pairing_term_indices(proto):
    """Objective entries belonging to a pairing rule, by variable name.

    `prefer_with` names its day variable `<rule>_gap_<day>`, so the terms are
    identifiable without threading anything new through the solver. Matching on
    the probe's own prefix rather than on `_gap_` alone keeps it from picking up
    a future rule that happens to name a variable the same way.
    """
    want = tuple(c['name'] for c in _pairing_rule_configs())
    out = []
    for pos, idx in enumerate(proto.objective.vars):
        name = proto.variables[idx].name or ''
        if name.startswith(want):
            out.append(pos)
    return out


def _reachable(proto, positions, seconds=PROBE_SECONDS):
    """(achieved, bound, status) for just these objective entries.

    Asked of CP-SAT, never computed — see the module docstring.
    """
    from ortools.sat.python import cp_model

    model = cp_model.CpModel()
    model.Proto().copy_from(proto)
    terms = []
    for pos in positions:
        idx = proto.objective.vars[pos]
        coeff = abs(int(proto.objective.coeffs[pos]))
        terms.append(model.GetIntVarFromProtoIndex(idx) * coeff)
    model.Proto().clear_objective()
    if not terms:
        return 0, 0, 'none'
    model.Maximize(sum(terms))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = seconds
    solver.parameters.num_workers = 4
    status = solver.Solve(model)
    if status == cp_model.INFEASIBLE:
        return 0, 0, 'INFEASIBLE'
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, None, solver.StatusName(status)
    return (int(solver.ObjectiveValue()), int(solver.BestObjectiveBound()),
            solver.StatusName(status))


@pytest.mark.slow
class TestThePairingBudget:
    def test_the_rules_are_actually_in_the_model(self, model_with_pairings):
        """The negative half. Without it every assertion below passes on a
        model containing no pairing term at all — measuring nothing, loudly."""
        proto = model_with_pairings['proto']
        positions = _pairing_term_indices(proto)
        assert positions, (
            'no pairing terms reached the objective: the fixture injected the '
            'rules but the solver did not score them, so this file is vacuous')

    def test_all_pairings_together_stay_inside_the_budget(
            self, model_with_pairings, capsys):
        proto = model_with_pairings['proto']
        positions = _pairing_term_indices(proto)
        achieved, bound, status = _reachable(proto, positions)
        # Printed, not just asserted. The budget is a [proposal] and the
        # headroom under it is what a later pairing gets to spend, so the
        # number is worth reading even on a pass — `pytest -s`.
        with capsys.disabled():
            frac = (bound / OBJECTIVE_TIER_WEIGHTS['medium']
                    if bound is not None else float('nan'))
            print(f'\n  pairing terms: {len(positions)} over '
                  f"{model_with_pairings['cells']} cells at {MAX_NUM_DAYS} days"
                  f'\n  reachable mass: bound={bound:,} achieved={achieved:,} '
                  f'({status})'
                  f'\n  budget {PAIRING_BUDGET:,} = 0.100 of a MEDIUM unit; '
                  f'measured {frac:.4f} of one\n')
        assert bound is not None, (
            f'CP-SAT did not decide ({status}); an UNKNOWN returns a bound of '
            f'0, which would read as "no mass" and pass this guard vacuously. '
            f'Raise PAIRING_BUDGET_PROBE_SECONDS (now {PROBE_SECONDS}).')
        assert bound <= PAIRING_BUDGET, (
            f'pairing mass reaches {bound:,} against a budget of '
            f'{PAIRING_BUDGET:,} ({bound / OBJECTIVE_TIER_WEIGHTS["medium"]:.3f} '
            f'of one MEDIUM unit, achieved {achieved:,}, {status}). A low-tier '
            f'rule that can outbid a medium one is note 32 happening again.')

    def test_the_budget_is_a_real_fraction_of_a_medium_unit(self):
        """Pins the number's meaning, not the number: a budget at or above one
        medium unit would permit exactly what it exists to forbid."""
        assert PAIRING_BUDGET < OBJECTIVE_TIER_WEIGHTS['medium']
        assert PAIRING_BUDGET >= OBJECTIVE_TIER_WEIGHTS['low']
