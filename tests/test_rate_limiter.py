"""Tests for the rate limiter module (TTL buckets + trusted-proxy IP lookup)."""

from types import SimpleNamespace

from digitaltwin.config import Settings
from digitaltwin.rate_limiter import RateLimiter, client_ip_from_request


def make_limiter(**overrides) -> RateLimiter:
    return RateLimiter(Settings(**overrides))


class TestRateLimiter:
    def test_allows_requests_within_limit(self):
        limiter = make_limiter(rate_limit_requests=3, rate_limit_window_seconds=60)
        assert all(not limiter.is_limited("1.1.1.1") for _ in range(3))

    def test_blocks_when_limit_exceeded(self):
        limiter = make_limiter(rate_limit_requests=2, rate_limit_window_seconds=60)
        assert limiter.is_limited("2.2.2.2") is False
        assert limiter.is_limited("2.2.2.2") is False
        assert limiter.is_limited("2.2.2.2") is True

    def test_keys_are_independent(self):
        limiter = make_limiter(rate_limit_requests=1, rate_limit_window_seconds=60)
        assert limiter.is_limited("a") is False
        assert limiter.is_limited("b") is False

    def test_empty_key_never_limited(self):
        assert make_limiter().is_limited("") is False

    def test_sweep_removes_idle_keys(self):
        import time

        limiter = make_limiter(rate_limit_window_seconds=60)
        # Insert a bucket with a timestamp far older than the window.
        limiter._requests["idle-key"] = [time.time() - 120.0]
        limiter._last_sweep = 0  # force sweep on next call
        limiter.is_limited("other-key")
        assert "idle-key" not in limiter._requests


class TestClientIPFromRequest:
    def _request(self, peer_host="1.2.3.4", headers=None):
        return SimpleNamespace(client=SimpleNamespace(host=peer_host), headers=headers or {})

    def test_defaults_to_localhost(self):
        assert client_ip_from_request(None) == "127.0.0.1"

    def test_peer_ip_used_when_no_trusted_proxies(self):
        req = self._request(peer_host="8.8.8.8", headers={"x-forwarded-for": "5.5.5.5"})
        assert client_ip_from_request(req) == "8.8.8.8"

    def test_forwarded_for_used_only_from_trusted_proxy(self):
        req = self._request(peer_host="10.0.0.1", headers={"x-forwarded-for": "5.5.5.5"})
        assert client_ip_from_request(req, trusted_proxies=("10.0.0.1",)) == "5.5.5.5"

    def test_forwarded_for_takes_leftmost_entry(self):
        req = self._request(peer_host="10.0.0.1", headers={"x-forwarded-for": "1.1.1.1, 2.2.2.2"})
        assert client_ip_from_request(req, trusted_proxies=("10.0.0.1",)) == "1.1.1.1"

    def test_untrusted_proxy_ignored(self):
        req = self._request(peer_host="6.6.6.6", headers={"x-forwarded-for": "5.5.5.5"})
        assert client_ip_from_request(req, trusted_proxies=("10.0.0.1",)) == "6.6.6.6"

    def test_wildcard_trusts_all(self):
        req = self._request(peer_host="6.6.6.6", headers={"x-forwarded-for": "5.5.5.5"})
        assert client_ip_from_request(req, trusted_proxies=("0.0.0.0/0",)) == "5.5.5.5"