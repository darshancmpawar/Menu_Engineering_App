"""Tests for the per-principal rate limiter."""

from __future__ import annotations

import pytest

from api import metrics
from api.rate_limit import (
    _LIMITS,
    _TokenBucketLimiter,
    rate_limit,
    reset_for_tests,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_for_tests()
    metrics.reset()
    yield
    reset_for_tests()
    metrics.reset()


class TestTokenBucketLimiterUnit:
    def test_first_N_requests_within_burst_succeed(self):
        limiter = _TokenBucketLimiter("t", capacity=3, refill_per_second=1.0)
        for _ in range(3):
            allowed, _ = limiter.try_acquire("u", now=100.0)
            assert allowed
        allowed, retry = limiter.try_acquire("u", now=100.0)
        assert allowed is False
        assert retry > 0, "retry_after must be positive on reject"

    def test_refill_after_time_elapsed(self):
        limiter = _TokenBucketLimiter("t", capacity=2, refill_per_second=2.0)
        limiter.try_acquire("u", now=100.0)
        limiter.try_acquire("u", now=100.0)
        allowed, _ = limiter.try_acquire("u", now=100.0)
        assert allowed is False
        # 0.5s at 2 tokens/sec = 1 fresh token.
        allowed, _ = limiter.try_acquire("u", now=100.5)
        assert allowed is True

    def test_capacity_is_upper_bound_on_refill(self):
        """A long idle must refill at most up to ``capacity``, not beyond,
        so a burst after being idle for hours still only allows ``capacity``
        acquires in a row."""
        limiter = _TokenBucketLimiter("t", capacity=2, refill_per_second=1000.0)
        limiter.try_acquire("u", now=100.0)   # bucket: 2 → 1
        # Very long idle — a naive impl would refill to a huge number here.
        # All at t = 200 (same instant, so no further refill between calls).
        allowed1, _ = limiter.try_acquire("u", now=200.0)
        allowed2, _ = limiter.try_acquire("u", now=200.0)
        allowed3, _ = limiter.try_acquire("u", now=200.0)
        assert allowed1 is True
        assert allowed2 is True
        assert allowed3 is False, (
            "bucket must have capped refill at capacity=2"
        )

    def test_different_keys_are_independent(self):
        limiter = _TokenBucketLimiter("t", capacity=1, refill_per_second=1.0)
        assert limiter.try_acquire("alice", now=100.0)[0] is True
        assert limiter.try_acquire("bob", now=100.0)[0] is True, (
            "one user exhausting the bucket must not affect another"
        )
        assert limiter.try_acquire("alice", now=100.0)[0] is False

    def test_retry_after_matches_refill_rate(self):
        # Capacity 1, refill 0.5 tokens/sec => after one grab we wait 2s.
        limiter = _TokenBucketLimiter("t", capacity=1, refill_per_second=0.5)
        limiter.try_acquire("u", now=100.0)
        allowed, retry = limiter.try_acquire("u", now=100.0)
        assert allowed is False
        assert abs(retry - 2.0) < 0.01, f"expected ~2s retry, got {retry}"

    def test_rejects_bad_config(self):
        with pytest.raises(ValueError):
            _TokenBucketLimiter("t", capacity=0, refill_per_second=1.0)
        with pytest.raises(ValueError):
            _TokenBucketLimiter("t", capacity=1, refill_per_second=0.0)


class TestRateLimitDecoratorViaFlask:
    """End-to-end through a real Flask app + test client."""

    @pytest.fixture
    def app(self, monkeypatch):
        from flask import Flask, g, jsonify

        # Shrink the plan limit so the test doesn't have to send 11 requests.
        monkeypatch.setitem(
            _LIMITS, "plan",
            _TokenBucketLimiter("plan", capacity=2, refill_per_second=0.001),
        )

        app = Flask(__name__)

        @app.before_request
        def _fake_auth():
            # Emulate what require_api_auth would have set.
            g.api_user = {"email": "alice@test.com", "role": "admin"}

        @app.route("/plan", methods=["POST"])
        @rate_limit("plan")
        def _plan():
            return jsonify({"success": True})

        @app.route("/by-ip", methods=["POST"])
        @rate_limit("plan")
        def _by_ip():
            # No auth_user → IP-based key.
            g.api_user = None
            return jsonify({"success": True})

        return app

    def test_429_when_bucket_empty(self, app):
        with app.test_client() as c:
            assert c.post("/plan").status_code == 200
            assert c.post("/plan").status_code == 200
            resp = c.post("/plan")
        assert resp.status_code == 429
        data = resp.get_json()
        assert data["success"] is False
        assert "Too many requests" in data["error"]
        assert resp.headers.get("Retry-After")
        assert int(resp.headers["Retry-After"]) >= 1

    def test_429_counter_is_bumped(self, app):
        with app.test_client() as c:
            c.post("/plan"); c.post("/plan"); c.post("/plan")  # 3rd rejects
        snap = metrics.snapshot()
        assert snap.get('rate_limit_allowed_total{limit="plan"}') == 2
        assert snap.get('rate_limit_rejected_total{limit="plan"}') == 1

    def test_different_users_have_separate_buckets(self, app):
        """Driving the key directly via before_request gives us tight
        control over who is 'calling' on each request."""
        from flask import g
        next_user = {"email": "alice@test.com"}

        @app.before_request
        def _switch_user():
            g.api_user = {"email": next_user["email"], "role": "admin"}

        with app.test_client() as c:
            # alice drains her bucket (capacity 2), third call gets 429.
            assert c.post("/plan").status_code == 200
            assert c.post("/plan").status_code == 200
            assert c.post("/plan").status_code == 429

            # Switch principal to bob — his bucket is untouched.
            next_user["email"] = "bob@test.com"
            assert c.post("/plan").status_code == 200
