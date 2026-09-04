"""The objective tiers must stay lexicographic, and that is arithmetic, not faith.

`OBJECTIVE_TIER_WEIGHTS` is 1e15 / 1e12 / 1e9 / 1e6 — a 1000x step between
adjacent tiers — and the whole soft-rule design rests on the claim that a
higher-priority preference is never traded away for a pile of lower ones
(rulebook section 7). CP-SAT does not know about tiers: it maximises one integer
sum. So the claim holds only while **everything below a tier, added up, stays
under one unit of it**, and that is a property of the plan's SIZE, not of the
constants. Enough low-tier terms and the ordering silently inverts — the solve
still returns OPTIMAL, having optimised the wrong priority, with nothing logged.
Same shape as the failure in design note 27: the quiet outcome is the dangerous
one.

`docs/EXPLAIN_LAYER_WORKORDER.md` (known issue 5) put the headroom at 1.75x from
an estimate of the term count. This measures it instead, on the model the real
solver builds for a real client config at `MAX_NUM_DAYS`.

**The measurement says the theme tier is inverted.** CP-SAT finds a feasible
assignment where the mass below THEME reaches ~1.02e15 against a 1e15 tier
weight, so a theme violation can be bought with high-tier gains. That is an
achieved solution rather than a loose bound, and the guard carries a strict
`xfail` naming it — the fix is a wider tier separation, which changes every menu
for every client and is therefore the client's decision, not a patch.

**Three bounds were tried and two were wrong**, which is why `_reachable_below`
asks CP-SAT rather than computing. That history is kept in its docstring
deliberately: each wrong bound looked obviously right, and the two of them
disagreed by a factor of ten on the same model.
"""

from __future__ import annotations

import pytest

# The horizon the API will accept. The whole point of this file is to measure at
# the ceiling a caller can actually reach, not at the 5-day default.
from api.config import MAX_NUM_DAYS
from src.constants import OBJECTIVE_TIER_WEIGHTS
from tests.client_fixtures import APP_SETTINGS, CLIENTS
from tests.fake_supabase import FakeSupabase

# Booking.com counter 0 is the fleet's widest: 19 expanded slots. Chosen by
# measurement (`max(sum(slot_counts[c] for c in categories))` over the
# fixtures), not by reputation — `test_the_widest_counter_is_still_this_one`
# fails if the fleet grows past it, because the headroom below is only
# meaningful for the worst case that actually exists.
WIDEST_CLIENT = 'Booking.com'
WIDEST_COUNTER = 0

MONDAY = '2026-08-03'

# `MenuSolver._build_objective`'s per-candidate random tie-break, `rng.randint(
# 0, 1000)` on the plan path. Sits above one freshness UNIT and below one LOW
# rule unit by design (note 24); named here so the bound below reads as
# arithmetic rather than a magic number.
MAX_TIE_BREAK = 1000



def _counter_width(client: dict, index: int) -> int:
    counter = (client.get('counters') or [])[index]
    counts = counter.get('slot_counts') or {}
    return sum(int(counts.get(c, 1)) for c in (counter.get('categories') or []))


@pytest.fixture
def live_clients(monkeypatch):
    import src.db as db_mod
    fake = FakeSupabase(seed={
        'clients': [dict(c) for c in CLIENTS],
        'app_settings': [dict(s) for s in APP_SETTINGS],
        'menu_history': [],
        'week_signatures': [],
    })
    monkeypatch.setattr(db_mod, '_sb_client', fake, raising=False)
    import api.app as api_app
    monkeypatch.setattr(api_app, '_client_loader', None, raising=False)
    api_app.reset_caches()
    api_app.app.config['TESTING'] = True
    return api_app


@pytest.fixture
def objective_coeffs(live_clients, monkeypatch):
    """Every objective coefficient CP-SAT is handed for one real 30-day model.

    Captured by letting the solver build the model and reading
    `model.Proto().objective.coeffs` — the numbers the optimiser actually sees.
    The solve itself is given a one-second budget and is allowed to fail: the
    objective is built before `Solve` runs, so a timeout costs nothing here.
    """
    from src.solver.menu_solver import MenuSolver

    captured: list = []
    original = MenuSolver._build_objective

    def _spy(self, model, cells, rng, similarity, context):
        original(self, model, cells, rng, similarity, context)
        # Read the coefficients back off the proto rather than re-deriving
        # them: this is the list CP-SAT optimises, so nothing is assumed about
        # how many bools a rule emitted. Wrapped because a probe must never be
        # the reason a solve fails — a raise here 500s the request and the
        # fixture would skip, which is the honest outcome but not a useful one.
        try:
            proto = model.Proto()
            obj = proto.objective
            reach = []
            for idx, coeff in zip(obj.vars, obj.coeffs):
                # Multiply by the variable's own range, not by 1. Most terms
                # are bools, but `avoid_attribute_repeat` returns IntVars whose
                # domain runs to the number of days a value recurs — treating
                # those as 0/1 understates the tier's reachable mass, which is
                # the whole quantity under test.
                dom = list(proto.variables[idx].domain)
                span = max(abs(v) for v in dom) if dom else 1
                reach.append(abs(int(coeff)) * max(1, int(span)))
        except Exception:                       # pragma: no cover - defensive
            return
        if reach:
            snapshot = type(proto)()
            snapshot.copy_from(proto)
            captured.append({'coeffs': reach, 'cells': len(cells),
                             'proto': snapshot})

    monkeypatch.setattr(MenuSolver, '_build_objective', _spy)

    with live_clients.app.test_client() as c:
        c.post('/api/v1/plan', json={
            'client_name': WIDEST_CLIENT,
            'counter_index': WIDEST_COUNTER,
            'start_date': MONDAY,
            'num_days': MAX_NUM_DAYS,
            'time_limit_seconds': 1,
        })

    if not captured:
        pytest.skip('the solver never reached _build_objective for this config')
    return max(captured, key=lambda c: len(c['coeffs']))   # the primary model


def _reachable_below(capture, weight, seconds=20):
    """The largest total the terms cheaper than `weight` can actually reach.

    **Asked of CP-SAT rather than computed here, because every arithmetic bound
    I tried was unsound in one direction or the other.** Summing coefficients
    treats competing variables as simultaneously satisfiable and understates an
    IntVar term (`avoid_attribute_repeat`'s recurrence counter reaches its
    domain, not 1). Multiplying each coefficient by its variable's range fixes
    that and then overstates badly, because those per-value maxima compete for
    the same days — one value recurring on every day is the others not
    appearing at all. The two gave 10x and 0.94x for the same model, which is
    the difference between "fine" and "shipped broken".

    So the model is re-solved with only the sub-`weight` terms as its objective
    and every original constraint intact. `BestObjectiveBound()` is a valid
    upper bound on a maximisation **even when the solve times out**, so a short
    budget yields a sound (if loose) answer rather than a wrong one — and when
    it proves optimality the answer is exact.

    Returns ``(achieved, bound, status)``. The two answer different questions
    and the test needs both: an ACHIEVED total at or above the tier's weight is
    a feasible solution that inverts the ordering, which *proves* the defect; a
    BOUND below it *proves* the ordering safe. Between the two the guard has
    not decided, and says so rather than passing.
    """
    from ortools.sat.python import cp_model

    proto, terms = capture['proto'], []
    model = cp_model.CpModel()
    model.Proto().copy_from(proto)
    for idx, coeff in zip(proto.objective.vars, proto.objective.coeffs):
        if abs(int(coeff)) < weight:
            terms.append(model.GetIntVarFromProtoIndex(idx)
                         * abs(int(coeff)))
    model.Proto().clear_objective()
    if not terms:
        return 0, 0, 'none'
    model.Maximize(sum(terms))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = seconds
    solver.parameters.num_workers = 4
    status = solver.Solve(model)
    if status == cp_model.INFEASIBLE:
        # The counter itself is unsatisfiable at this horizon; nothing below
        # the tier is reachable, so the ladder holds trivially.
        return 0, 0, 'INFEASIBLE'
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # UNKNOWN: no solution found, and `BestObjectiveBound()` has nothing
        # behind it — it returns 0 here, which read as "nothing is reachable"
        # and would have turned a timeout into a clean bill of health. `None`
        # means undecided, and the caller has to say so.
        return None, None, solver.StatusName(status)
    return (int(solver.ObjectiveValue()), int(solver.BestObjectiveBound()),
            solver.StatusName(status))


def _band_totals(capture):
    """Per-tier upper bounds on what the objective can actually reach.

    Two different sums, because the terms come in two shapes and only one of
    them can all be 1 at once:

      * **rule terms** attach to auxiliary bools (`sum(bools) * -w`), which are
        independent — so their upper bound is simply the sum of the band.
      * **freshness and the tie-break** attach to per-CANDIDATE variables, and
        every cell has an exactly-one constraint over its candidates. Summing
        them all overstates the reachable total by the pool size — about 50x
        here. The reachable bound is `cells * the largest per-cell coefficient`.

    Getting that distinction wrong is the difference between "the objective is
    broken" and "the objective is fine", so it is spelled out rather than
    folded into a comprehension.

    The sub-rule band uses the CONSTANTS, not the sampled coefficients. A
    fixture with no saved history scores every freshness bonus at 0 (design
    note 24: an empty recency map yields no bonus), which is the best case and
    would let this whole file pass while measuring nothing — the same vacuous
    guard the ontology audits keep planting misfiles to avoid. `_potential`
    is what the band reaches once a client has history, which every real one
    does within a week.
    """
    from src.solver.menu_solver import MAX_FRESHNESS_BONUS

    coeffs, n_cells = capture['coeffs'], capture['cells']
    weights = sorted(OBJECTIVE_TIER_WEIGHTS.values())        # low .. theme
    low = weights[0]
    per_cell = MAX_FRESHNESS_BONUS + MAX_TIE_BREAK
    bands = {'sub_rule': n_cells * per_cell}
    for name, w in OBJECTIVE_TIER_WEIGHTS.items():
        upper = min((x for x in weights if x > w), default=None)
        bands[name] = sum(c for c in coeffs
                          if c >= w and (upper is None or c < upper))
    return bands


# The most high-priority soft rules any single counter can load: 4 from the
# widest city ruleset (Pune), plus 0 that any client file adds. This is the
# DRIVER of theme-tier inversion, and pinning it is what makes the measured
# headroom the fleet's real worst case rather than one fixture's luck — see
# `TestWhatWouldActuallyInvertTheThemeTier`.
MAX_HIGH_TIER_CITY_RULES = 4
MAX_HIGH_TIER_CLIENT_RULES = 0


def _high_tier_rule_counts():
    """(most in any city ruleset, most any client file adds).

    Kept as two numbers because a counter loads exactly one city ruleset plus
    its own client block — summing across cities would describe a config that
    cannot exist.
    """
    import json
    import pathlib

    def _high(rules):
        return sum(1 for r in rules if isinstance(r, dict)
                   and r.get('type') == 'soft_preference'
                   and r.get('priority') == 'high')

    root = pathlib.Path(__file__).resolve().parents[2] / 'data' / 'configs'
    city = max((_high(json.loads(p.read_text(encoding='utf-8')).get('rules', []))
                for p in sorted(root.glob('city_rules/*.json'))), default=0)
    client = 0
    for path in sorted(root.glob('clients/*.json')):
        for spec in json.loads(path.read_text(encoding='utf-8')).values():
            rules = spec.get('rules', []) if isinstance(spec, dict) else spec
            client = max(client, _high(rules))
    return city, client


class TestWhatWouldActuallyInvertTheThemeTier:
    """The theme tier has the whole ladder beneath it, so it is the thin rung.

    A tempting bound is `theme_weight / (cells x high_weight)` — break-even at
    1,000 cells, and `client_config` permits 22 base slots x 5 x 30 days =
    3,300, so the config space would already contain inverted states. That
    bound is not right: **HIGH terms do not attach to cells.** Every mode of
    `soft_preference` returns `sum(<vars>) * -w`, and those vars are auxiliary
    — one per day, per day-pair, or per (day, attribute value). The measured
    model has 516 cells and far fewer HIGH-weighted variables.

    But "not per cell" is not the same as "small", and one mode is subtler than
    the rest: `avoid_attribute_repeat` returns **IntVars** whose domain runs to
    the number of days a value recurs. Counting those as 0/1 understates the
    reachable mass, which is exactly the quantity under test — so the capture
    multiplies every coefficient by its variable's own range. The first version
    of this file did not, and would have reported a comfortable ladder while
    the real figure was several times larger.

    The driver, then, is the number of high-priority soft rules a counter can
    load and the arity of each. That is exact and needs no solve, so it is
    pinned here; the measured ratio below is only valid at these counts.
    """

    def test_the_high_tier_rule_count_has_not_grown(self):
        city, client = _high_tier_rule_counts()
        assert (city, client) == (MAX_HIGH_TIER_CITY_RULES,
                                  MAX_HIGH_TIER_CLIENT_RULES), (
            f'high-priority soft rules: {city} in the widest city ruleset, '
            f'{client} added by a client file; pinned at '
            f'{MAX_HIGH_TIER_CITY_RULES}/{MAX_HIGH_TIER_CLIENT_RULES}. The '
            'theme-tier headroom below was measured at those counts — re-run '
            '`pytest tests/rules/test_objective_tier_headroom.py -m slow` and '
            'update the pins, or the ladder is no longer known to hold.')

    def test_high_tier_terms_are_per_day_not_per_cell(self):
        """The premise of the bound, as an executable note.

        Every mode builds its penalty variables in a `for di in range(n)` loop
        over DAYS. Candidates are read inside that loop to decide which day
        carries which value, but the variable that reaches the objective is
        per-day, not per-candidate. If that ever changes, the reasoning above
        needs revisiting rather than the number being bumped.
        """
        import inspect
        from src.menu_rules.soft_preference_rule import SoftPreferenceRule
        src = inspect.getsource(SoftPreferenceRule.get_objective_terms)
        assert 'for di in range(n)' in src
        # Every return is a single weighted sum, so one coefficient per term.
        returns = [l.strip() for l in src.splitlines()
                   if 'return [' in l and l.strip() != 'return []']
        assert returns and all('abs(w)' in l for l in returns), returns

    def test_an_intvar_term_is_measured_by_its_range(self):
        """The correction itself, pinned on a model built by hand.

        `avoid_attribute_repeat`'s `over` var counts recurrences, so its
        contribution is `w x domain`, not `w`. A guard that read coefficients
        alone would under-report the tier it exists to protect.
        """
        from ortools.sat.python import cp_model
        m = cp_model.CpModel()
        b = m.NewBoolVar('b')
        n = m.NewIntVar(0, 7, 'n')
        w = OBJECTIVE_TIER_WEIGHTS['high']
        m.Maximize(b * w + n * w)
        proto = m.Proto()
        reach = []
        for idx, coeff in zip(proto.objective.vars, proto.objective.coeffs):
            dom = list(proto.variables[idx].domain)
            reach.append(abs(int(coeff)) * max(1, max(abs(v) for v in dom)))
        assert sorted(reach) == [w, 7 * w]


@pytest.mark.slow
class TestTheTiersStayLexicographic:
    def test_the_widest_counter_is_still_this_one(self):
        """The headroom below is the fleet's WORST case or it means nothing."""
        by_name = {c['name']: c for c in CLIENTS}
        widest = max(
            ((_counter_width(c, i), c['name'], i)
             for c in CLIENTS for i in range(len(c.get('counters') or []))),
        )
        assert widest[1:] == (WIDEST_CLIENT, WIDEST_COUNTER), widest
        assert _counter_width(by_name[WIDEST_CLIENT], WIDEST_COUNTER) == widest[0]

    @pytest.mark.xfail(
        strict=True,
        reason=(
            'KNOWN DEFECT, reproduced: on the fleet''s widest counter at '
            'MAX_NUM_DAYS the mass below the THEME tier reaches ~1.02e15 '
            'against a 1e15 tier weight, so a theme violation can be bought '
            'with high-tier gains. CP-SAT finds a real assignment that does '
            'it, so this is not a loose bound. The fix is a wider tier '
            'separation, which changes every menu for every client — a '
            'decision for the client, not a patch. Remove this marker with '
            'that change; `strict` makes the test fail if it starts passing '
            'while the marker is still here.'),
    )
    def test_every_rule_tier_outranks_everything_beneath_it(self, objective_coeffs):
        """Rulebook section 7, measured: a higher-priority soft rule is never
        traded away for a pile of lower-priority ones.

        When this fails, a menu comes back OPTIMAL having optimised the wrong
        priority — no exception, no log line, nothing red. It is the same
        silent-wrongness shape as design note 27, which is why it is worth a
        real model rather than an estimate.

        Theme is the rung that fails, and structurally it is the one to watch:
        it has the whole ladder beneath it. Medium and high read comfortable
        only because they sit under fewer tiers, so reporting all three as
        "comfortable" hides the one that matters.
        """
        inverted = []
        # LOW is deliberately not one of the rungs checked here — see
        # `test_freshness_is_a_plan_level_preference_not_a_per_cell_one`.
        print('\nreachable mass below each tier:')
        for name in ('medium', 'high', 'theme'):
            weight = OBJECTIVE_TIER_WEIGHTS[name]
            achieved, bound, status = _reachable_below(objective_coeffs, weight)
            shown = ('undecided' if achieved is None
                     else f'achieved {achieved:,} / bound {bound:,}')
            print(f'  {name:<7} {shown}  [{status}]')
            if achieved is not None and achieved >= weight:
                inverted.append(
                    f'{name}: a FEASIBLE solution reaches {achieved:,} below '
                    f'the tier, >= one {name} unit ({weight:,})')
        assert not inverted, (
            'the objective is NOT lexicographic at MAX_NUM_DAYS on the '
            "fleet's widest counter — a real assignment, not a loose bound: "
            + '; '.join(inverted)
            + '. Widen the separation in OBJECTIVE_TIER_WEIGHTS. NB a uniform '
              '1e4 step would break the other end: freshness reaches 91,000 in '
              'a cell and must stay under one LOW unit (note 24), so LOW '
              'cannot drop to 1e4. Do not change the freshness constants in '
              'the same commit (note 32).')

    def test_freshness_is_a_plan_level_preference_not_a_per_cell_one(
            self, objective_coeffs):
        """The one rung the ladder does NOT have, stated rather than assumed.

        Design note 24 picked `MAX_FRESHNESS_BONUS` (90,000) to sit under one
        LOW unit (1e6) so "any rule outranks freshness" — and that holds **in a
        cell**, which is the scope the note gives it and what
        `test_freshness_never_outbids_a_rule_inside_one_cell` pins. It does not
        hold across a plan: freshness is one bonus per CELL, so on this counter
        at MAX_NUM_DAYS the band reaches tens of LOW units and the solver may
        accept several low-priority violations in exchange for fresher dishes.

        That is a menu-policy question (is freshness worth one low-priority
        violation? five?), not a constant to quietly retune — changing either
        weight changes every menu for every client. So the ladder above skips
        this rung, and the ratio is printed for whoever decides. What IS pinned
        is the bound that matters for correctness: even at full stretch the
        band cannot reach a MEDIUM rule.
        """
        bands = _band_totals(objective_coeffs)
        low, medium = (OBJECTIVE_TIER_WEIGHTS['low'],
                       OBJECTIVE_TIER_WEIGHTS['medium'])
        print(f'\n  freshness band reaches {bands["sub_rule"]:,} = '
              f'{bands["sub_rule"] / low:,.1f} LOW units '
              f'({bands["sub_rule"] / medium:.4f} of a MEDIUM unit)')
        assert bands['sub_rule'] + bands['low'] < medium, (
            'freshness plus the low tier can now outrank a MEDIUM soft rule '
            f'({bands["sub_rule"] + bands["low"]:,} >= {medium:,}). That is no '
            'longer a policy question — it breaks the tier design.')

    def test_freshness_never_outbids_a_rule_inside_one_cell(self,
                                                            objective_coeffs):
        """Design note 24's actual claim, which is per-CELL.

        `MAX_FRESHNESS_BONUS` (90,000) sits below one LOW unit (1e6) so a real
        rule always wins the choice of dish for a cell. That is the guarantee
        the constant was picked for, and it is separate from — and weaker than —
        the plan-wide question the two tests above ask.
        """
        from src.solver.menu_solver import MAX_FRESHNESS_BONUS

        low = OBJECTIVE_TIER_WEIGHTS['low']
        sub = [c for c in objective_coeffs['coeffs'] if c < low]
        assert sub, 'no freshness / tie-break terms — the fixture stopped '
        assert max(sub) < low
        # And the bound the constant promises, not just the sample.
        assert MAX_FRESHNESS_BONUS + 1000 < low
