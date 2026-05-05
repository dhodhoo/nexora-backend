from __future__ import annotations

from collections import defaultdict
from datetime import date

from fastapi import HTTPException


class BroadcastRateLimiter:
    def __init__(self) -> None:
        self._counts: dict[str, int] = defaultdict(int)

    def check_and_increment(
        self,
        user_id: str,
        limit: int = 5,
        bucket: str = "broadcast",
        error_message: str = "Rate limit exceeded",
    ) -> None:
        today = date.today().isoformat()
        key = f"{bucket}:{user_id}:{today}"
        current = self._counts.get(key, 0)
        if current >= limit:
            raise HTTPException(status_code=429, detail=error_message)
        self._counts[key] = current + 1


broadcast_rate_limiter = BroadcastRateLimiter()
