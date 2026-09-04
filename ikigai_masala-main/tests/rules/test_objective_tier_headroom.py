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

`docs/EXPLAIN_LAYER_WORKORDER.md` (known issue 5) put the headroom at 1.75x for
the fleet's widest counter at `MAX_NUM_DAYS`, from an estimate of the term
count. This measures it instead. The model is built by the real solver against a
real client config and the coefficients are read back off the CP-SAT proto, so
the number here is what CP-SAT actually sees — no assumption about how many
bools a rule emits, which is the part an estimate has to guess and the part that
changes whenever a rule is added.
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


# Bands from cheapest to dearest. `sub_rule` is freshness + the tie-break,
# which is not a rule tier at all — it sits under all of them.
_ORDER = ['sub_rule'] + [n for n, _ in sorted(OBJECTIVE_TIER_WEIGHTS.items(),
                                              key=lambda kv: kv[1])]


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
            coeffs = [abs(int(c)) for c in model.Proto().objective.coeffs]
        except Exception:                       # pragma: no cover - defensive
            return
        if coeffs:
            captured.append({'coeffs': coeffs, 'cells': len(cells)})

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

    def test_every_rule_tier_outranks_everything_beneath_it(self, objective_coeffs):
        """Rulebook section 7, measured: a higher-priority soft rule is never
        traded away for a pile of lower-priority ones.

        If this fails, a menu comes back OPTIMAL having optimised the wrong
        priority — no exception, no log line, nothing red. It is the same
        silent-wrongness shape as design note 27, which is why it is worth a
        real model rather than an estimate.
        """
        bands, failures = _band_totals(objective_coeffs), []
        print('\nreachable objective mass by band:')
        for name in _ORDER:
            print(f'  {name:<9} {bands[name]:>20,}')
        # LOW is deliberately not one of the rungs checked here — see
        # `test_freshness_is_a_plan_level_preference_not_a_per_cell_one`.
        for i, name in enumerate(_ORDER):
            if name in ('sub_rule', 'low'):
                continue
            weight = OBJECTIVE_TIER_WEIGHTS[name]
            beneath = sum(bands[b] for b in _ORDER[:i])
            if beneath >= weight:
                failures.append(
                    f'{name}: everything below it can reach {beneath:,}, '
                    f'>= one {name} unit ({weight:,})')
        assert not failures, (
            'the objective is no longer lexicographic at MAX_NUM_DAYS on the '
            'fleet\'s widest counter: ' + '; '.join(failures)
            + '. Widen the separation in OBJECTIVE_TIER_WEIGHTS, or normalise '
              'each tier\'s contribution before summing.')

    def test_the_headroom_is_not_thin(self, objective_coeffs):
        """Early warning. The guarantee above is binary and gives no notice; a
        ratio that has quietly fallen to 1.1x is one new soft rule away from a
        silently wrong menu, and this is where that shows up first."""
        bands, thin = _band_totals(objective_coeffs), {}
        for i, name in enumerate(_ORDER):
            if name in ('sub_rule', 'low'):
                continue
            beneath = sum(bands[b] for b in _ORDER[:i])
            ratio = (float('inf') if not beneath
                     else OBJECTIVE_TIER_WEIGHTS[name] / beneath)
            print(f'  {name:<9} headroom x{ratio:,.2f}')
            if ratio < 1.5:
                thin[name] = round(ratio, 2)
        assert not thin, (
            f'tier headroom has fallen below 1.5x: {thin}. Still correct, but '
            'the next soft rule added to this counter may invert the ordering. '
            'See docs/EXPLAIN_LAYER_WORKORDER.md, known issue 5.')

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
