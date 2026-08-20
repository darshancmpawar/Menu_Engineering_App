"""Tests for internal ``menu_solver`` helpers (cell lookup)."""

from src.solver.menu_solver import _find_cells, _make_find_cells, _combo_day_variant
from src.constants import combo_minority_count


class TestComboSplit:
    def test_minority_count_anchored_to_2_of_5(self):
        assert combo_minority_count(5) == 2   # 3 majority + 2 minority
        assert combo_minority_count(7) == 3   # 4 majority + 3 minority
        assert combo_minority_count(6) == 2
        assert combo_minority_count(1) == 0   # single day → all majority
        assert combo_minority_count(0) == 0

    def test_minority_never_exceeds_majority(self):
        for n in range(1, 21):
            assert combo_minority_count(n) <= n // 2

    def test_dal_rasam_alternates_across_the_week(self):
        """Client rule: "when the combined slots are used it should alternate".

        The minority used to fill the last `combo_minority_count(n)` days, so a
        working week ran dal / dal / dal / rasam / rasam — three days of one and
        then two of the other, which is exactly what the client asked not to
        happen. The counts are unchanged; only the placement is.
        """
        got = [_combo_day_variant('dal_rasam', di, 5) for di in range(5)]
        assert got == ['dal', 'rasam', 'dal', 'rasam', 'dal']

    def test_sambar_rasam_alternates_across_the_week(self):
        got = [_combo_day_variant('sambar_rasam', di, 5) for di in range(5)]
        assert got == ['rasam', 'sambar', 'rasam', 'sambar', 'rasam']

    def test_dal_sambar_alternates_across_the_week(self):
        got = [_combo_day_variant('dal_sambar', di, 5) for di in range(5)]
        assert got == ['dal', 'sambar', 'dal', 'sambar', 'dal']

    def test_the_minority_never_lands_on_consecutive_days(self):
        """The property that makes it an alternation rather than a reshuffle.
        `combo_minority_count` keeps the minority at or under half the horizon,
        so an even spread can always avoid putting two together.
        """
        from src.constants import COMBO_CATEGORIES
        for combo, (_majority, minority) in COMBO_CATEGORIES.items():
            for n in range(2, 22):
                got = [_combo_day_variant(combo, di, n) for di in range(n)]
                pairs = [(a, b) for a, b in zip(got, got[1:])]
                assert (minority, minority) not in pairs, (combo, n, got)

    def test_the_split_keeps_the_configured_counts(self):
        """Spreading must not change how many days each component gets."""
        from src.constants import COMBO_CATEGORIES
        for combo, (_majority, minority) in COMBO_CATEGORIES.items():
            for n in range(1, 22):
                got = [_combo_day_variant(combo, di, n) for di in range(n)]
                assert got.count(minority) == combo_minority_count(n), (combo, n)


class TestComboRegistration:
    """Guards that every combination category is fully wired up. A combo that
    is registered in COMBO_CATEGORIES but missing from any of these sets fails
    silently at solve time (e.g. its minority pool empties on off-theme days
    and the split collapses to all-majority)."""

    def test_every_combo_is_cuisine_exempt(self):
        # A combo's minority component is often a different cuisine (South
        # sambar/rasam in a North week). It must be exempt from theme/cuisine
        # filtering or the minority pool empties on off-theme days.
        from src.constants import COMBO_CATEGORIES, EXEMPT_FROM_CUISINE
        for combo in COMBO_CATEGORIES:
            assert combo in EXEMPT_FROM_CUISINE, f"{combo} not cuisine-exempt"

    def test_every_combo_registered_as_slot(self):
        from src.constants import (
            COMBO_CATEGORIES, BASE_SLOT_NAMES, DEFAULT_OFF_SLOTS,
            DISPLAY_SLOT_NAME,
        )
        for combo in COMBO_CATEGORIES:
            assert combo in BASE_SLOT_NAMES, f"{combo} missing from BASE_SLOT_NAMES"
            assert combo in DEFAULT_OFF_SLOTS, f"{combo} missing from DEFAULT_OFF_SLOTS"
            assert combo in DISPLAY_SLOT_NAME, f"{combo} missing display label"


class _Stub:
    __slots__ = ("d_idx", "base_slot")

    def __init__(self, d_idx, base_slot):
        self.d_idx = d_idx
        self.base_slot = base_slot


def _sample_cells():
    return [
        _Stub(0, "bread"),
        _Stub(0, "rice"),
        _Stub(0, "rice"),
        _Stub(1, "bread"),
        _Stub(1, "starter"),
    ]


class TestLinearFindCells:
    def test_returns_matching_cells(self):
        cells = _sample_cells()
        out = _find_cells(cells, 0, "rice")
        assert [c.base_slot for c in out] == ["rice", "rice"]

    def test_returns_empty_when_no_match(self):
        assert _find_cells(_sample_cells(), 2, "bread") == []


class TestIndexedFindCells:
    def test_matches_linear_variant_for_all_keys(self):
        cells = _sample_cells()
        find = _make_find_cells(cells)
        for di in range(3):
            for slot in ("bread", "rice", "starter", "welcome_drink"):
                assert find(cells, di, slot) == _find_cells(cells, di, slot)

    def test_missing_key_returns_empty(self):
        find = _make_find_cells(_sample_cells())
        assert find([], 9, "nonexistent") == []

    def test_closure_ignores_first_arg(self):
        # The closure closes over cells at build time; the first arg is a
        # vestigial signature artifact kept for rule call-site compatibility.
        find = _make_find_cells(_sample_cells())
        assert find([], 0, "rice") == find(_sample_cells(), 0, "rice")
