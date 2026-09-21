"""In-memory sliding-window rate limiter with FastAPI dependency integration."""

import random
import time
from collections import deque

from fastapi import HTTPException, Request

from reasons_service.config import settings
from reasons_service.rbac import Role


class RateLimiter:
    """Sliding-window rate limiter using per-key timestamp deques.

    Single-process only. In multi-worker deployments each worker tracks
    independently, so effective limits scale with worker count.
    """

    def __init__(self):
        self._windows: dict[str, deque[float]] = {}

    def check(self, key: str, limit: int, window: float) -> tuple[bool, dict[str, str]]:
        now = time.monotonic()
        cutoff = now - window

        dq = self._windows.get(key)
        if dq is None:
            dq = deque()
            self._windows[key] = dq

        while dq and dq[0] <= cutoff:
            dq.popleft()

        remaining = max(0, limit - len(dq))
        headers = {
            "X-RateLimit-Limit": str(limit),
            "X-RateLimit-Remaining": str(max(0, remaining - 1)),
        }

        if len(dq) >= limit:
            retry_after = str(int(dq[0] - cutoff) + 1)
            headers["Retry-After"] = retry_after
            headers["X-RateLimit-Remaining"] = "0"
            return False, headers

        dq.append(now)

        if random.randint(1, 100) == 1:
            self._cleanup(cutoff)

        return True, headers

    def _cleanup(self, cutoff: float):
        stale = [k for k, dq in self._windows.items() if not dq or dq[-1] <= cutoff]
        for k in stale:
            del self._windows[k]


_limiter = RateLimiter()


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _get_limit(tier: str, user) -> int:
    if user and (user.role == Role.ADMIN or user.identity in ("api", "dev")):
        limit = settings.rate_limit_admin
        if limit == 0:
            return 0
        if tier == "chat":
            return settings.rate_limit_chat * 6
        return limit

    if not user or user.identity == "public":
        if tier == "chat":
            return settings.rate_limit_chat
        if tier == "search":
            return settings.rate_limit_public // 2
        return settings.rate_limit_public

    if tier == "chat":
        return settings.rate_limit_chat
    if tier == "search":
        return settings.rate_limit_search
    return settings.rate_limit_default


def require_rate_limit(tier: str = "default"):
    async def _check_rate_limit(request: Request):
        if not settings.rate_limit_enabled:
            return

        user = getattr(request.state, "user", None)

        limit = _get_limit(tier, user)
        if limit == 0:
            return

        if user and user.identity not in ("public",):
            key = f"user:{user.identity}:{tier}"
        else:
            key = f"ip:{_get_client_ip(request)}:{tier}"

        allowed, headers = _limiter.check(key, limit, settings.rate_limit_window)

        request.state.rate_limit_headers = headers

        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers=headers,
            )

    return _check_rate_limit
