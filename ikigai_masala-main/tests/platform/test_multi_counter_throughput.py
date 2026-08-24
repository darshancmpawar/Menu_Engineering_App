"""One Generate click on a multi-counter client must not exhaust the limiter.

The planner solves each counter with its own ``POST /plan`` — counter
coordination is client-orchestrated (note 22) — so one press of Generate on a
six-counter client is SIX requests. The ``plan`` bucket held ten, which meant a
user got one click and then ran out part-way through the second: the counters
after the cutoff came back 429 and their tabs had no menu at all.

That is the exact workload ``api/rate_limit.py``'s docstring promises a human
will never hit ("a user clicking through the planner should never hit these"),
and it became false when multi-counter clients arrived. The bucket is now sized
in *clicks* — ``MAX_COUNTERS * _PLAN_BURST_CLICKS`` — so the two numbers cannot
drift apart.

The second half was the client's retry. A 429 is not transient the way a 502 is:
the bucket refills at a known rate and the server says how long in
``Retry-After``. ``_with_one_retry`` slept its 0.2-0.7s jitter instead, and
``plan`` refills 0.3 tokens a second, so the retry could never produce a token
and the second request 429'd too.
"""

from __future__ import annotations

import pytest

from api.rate_limit import (
    _LIMITS, _PLAN_BURST_CLICKS, MAX_COUNTERS, reset_for_tests,
)
from ui.api_client import (
    _RETRY_AFTER_MAX_SEC, _retry_after_seconds, _with_one_retry,
)


class _Resp:
    def __init__(self, status_code, headers=None):
        self.status_code = status_code
        self.headers = headers or {}


class TestThePlanBucketHoldsAWholeClick:
    def test_it_fits_the_largest_possible_client(self):
        """Sized from MAX_COUNTERS rather than a literal, so raising the counter
        ceiling cannot silently re-break this."""
        assert _LIMITS['plan'].capacity >= MAX_COUNTERS
        assert _LIMITS['plan'].capacity == MAX_COUNTERS * _PLAN_BURST_CLICKS

    def test_it_fits_more_than_one_click(self):
        """One click's worth would still fail the moment a user pressed Generate
        twice — which is the reported symptom, not an edge case."""
        assert _PLAN_BURST_CLICKS >= 2

    def test_a_six_counter_client_can_generate_three_times(self):
        """The behavioural assertion, against the limiter itself so it needs no
        solve: 18 consecutive counter-requests all get a token."""
        reset_for_tests()
        limiter = _LIMITS['plan']
        allowed = 0
        for _ in range(MAX_COUNTERS * _PLAN_BURST_CLICKS):
            ok, _retry_after = limiter.try_acquire('an-ip', now=1000.0)
            allowed += 1 if ok else 0
        assert allowed == MAX_COUNTERS * _PLAN_BURST_CLICKS

    def test_it_still_throttles_a_loop(self):
        """The limiter's actual purpose. One request past the burst is refused,
        and it says how long to wait."""
        reset_for_tests()
        limiter = _LIMITS['plan']
        for _ in range(int(limiter.capacity)):
            limiter.try_acquire('an-ip', now=1000.0)
        ok, retry_after = limiter.try_acquire('an-ip', now=1000.0)
        assert ok is False
        assert retry_after and retry_after > 0

    def test_the_refill_rate_matches_the_capacity(self):
        """Capacity is a burst; the sustained rate is the same number a minute,
        so a user who waits a minute gets their clicks back."""
        limiter = _LIMITS['plan']
        assert limiter.refill_per_second == pytest.approx(
            limiter.capacity / 60.0)


class TestTheClientHonoursRetryAfter:
    def test_it_waits_the_header_not_the_jitter(self):
        slept = []
        responses = [_Resp(429, {'Retry-After': '3'}), _Resp(200)]
        out = _with_one_retry(
            lambda: responses.pop(0), retryable=True, sleep=slept.append)
        assert out.status_code == 200
        assert slept == [3.0], slept

    def test_it_caps_an_absurd_header(self):
        """This runs inside a Streamlit rerun — a server saying "wait an hour"
        must not park the UI."""
        slept = []
        responses = [_Resp(429, {'Retry-After': '3600'}), _Resp(200)]
        _with_one_retry(
            lambda: responses.pop(0), retryable=True, sleep=slept.append)
        assert slept == [_RETRY_AFTER_MAX_SEC]

    @pytest.mark.parametrize("headers", [
        {}, {'Retry-After': 'soon'}, {'Retry-After': '0'}, {'Retry-After': '-5'},
    ])
    def test_a_missing_or_junk_header_falls_back_to_jitter(self, headers):
        slept = []
        responses = [_Resp(429, headers), _Resp(200)]
        _with_one_retry(
            lambda: responses.pop(0), retryable=True, sleep=slept.append)
        assert len(slept) == 1
        assert 0.2 <= slept[0] <= 0.7, slept

    def test_a_502_still_uses_jitter(self):
        """Only 429 carries a meaningful Retry-After; a proxy hiccup should not
        be delayed by a header it happens to send."""
        slept = []
        responses = [_Resp(502, {'Retry-After': '30'}), _Resp(200)]
        _with_one_retry(
            lambda: responses.pop(0), retryable=True, sleep=slept.append)
        assert 0.2 <= slept[0] <= 0.7, slept

    def test_the_header_is_only_read_on_429(self):
        assert _retry_after_seconds(_Resp(503, {'Retry-After': '4'})) is None
        assert _retry_after_seconds(_Resp(429, {'Retry-After': '4'})) == 4.0

    def test_a_success_is_never_slept_on(self):
        slept = []
        _with_one_retry(lambda: _Resp(200), retryable=True, sleep=slept.append)
        assert slept == []
