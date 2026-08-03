"""Per-client-IP rate limiting with automatic TTL cleanup.

Unlike a plain dict that grows forever (IPs that never return leave stale
entries behind), this module keeps a bounded in-memory store. Entries older
than the window are pruned lazily on each check *and* a periodic sweep
removes idle buckets entirely so memory cannot grow without bound.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field

from .config import Settings
from .logger import get_logger

logger = get_logger(__name__)

# A capped sweep interval (seconds) is safe to hardcode: it only controls
# housekeeping frequency, not security semantics.
_SWEEP_INTERVAL_SECONDS = 60.0


@dataclass
class RateLimiter:
    """Token-bucket-ish sliding-window limiter keyed by a client identifier.

    Arbitrary keys are supported (not just IPs) so future backends
    (e.g. authenticated users) can reuse the same class.
    """

    settings: Settings
    _requests: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def is_limited(self, key: str) -> bool:
        """Return True if ``key`` has exceeded the rate limit.

        Also performs opportunistic pruning of expired timestamps for the
        given key, and a full sweep if enough time has passed.
        """
        if not key:
            return False
        now = time.time()
        window = float(self.settings.rate_limit_window_seconds)
        limit = self.settings.rate_limit_requests
        self._sweep_if_due(now)

        with self._lock:
            bucket = self._requests.get(key, [])
            # Drop timestamps outside the window.
            bucket = [t for t in bucket if now - t < window]
            if len(bucket) >= limit:
                self._requests[key] = bucket
                return True
            bucket.append(now)
            self._requests[key] = bucket
            return False

    def _sweep_if_due(self, now: float) -> None:
        """Periodically remove buckets that are empty or fully expired.

        Without this, an attacker could force unbounded memory growth by
        spraying many unique keys; expired entries are pruned per-key on
        access, but keys that *never* return would otherwise linger forever.
        """
        # Cheap early-out to avoid locking on every request.
        if not hasattr(self, "_last_sweep"):
            self._last_sweep = now
            return
        if now - self._last_sweep < _SWEEP_INTERVAL_SECONDS:
            return
        self._last_sweep = now

        window = float(self.settings.rate_limit_window_seconds)
        with self._lock:
            expired = [
                key
                for key, timestamps in self._requests.items()
                if not timestamps or now - timestamps[-1] >= window
            ]
            for key in expired:
                del self._requests[key]


def client_ip_from_request(
    request: object | None, trusted_proxies: tuple[str, ...] = ()
) -> str:
    """Return the best-effort client IP for a Gradio request.

    When running behind a reverse proxy (e.g. nginx/Traefik), the direct TCP
    peer is the proxy itself and the real client is in ``X-Forwarded-For``.
    We only honor that header when the peer address is in ``trusted_proxies``;
    otherwise an attacker could spoof arbitrary IPs to bypass the rate limit.
    """
    host = "127.0.0.1"
    if request is None:
        return host

    client = getattr(request, "client", None)
    if client is None:
        return host
    peer_ip = getattr(client, "host", None) or host

    # Honor X-Forwarded-For only from trusted proxies.
    if _is_trusted_proxy(peer_ip, trusted_proxies):
        headers = getattr(request, "headers", None)
        if headers is not None:
            forwarded = headers.get("x-forwarded-for", "")
            if forwarded:
                # X-Forwarded-For is a comma-separated list; the leftmost
                # entry is the original client.
                first = forwarded.split(",")[0].strip()
                if first:
                    return first
    return peer_ip


def _is_trusted_proxy(peer_ip: str, trusted_proxies: tuple[str, ...]) -> bool:
    if not trusted_proxies:
        return False
    if "0.0.0.0/0" in trusted_proxies:
        return True
    return peer_ip in trusted_proxies