"""
Test Fakes
==========
In-memory substitutes for external services.

Import FakeRedis directly in tests that need a Redis-shaped object
without the global monkeypatch (e.g., when injecting it into a service
constructor instead of patching the module-level client).

    from tests.fakes import FakeRedis
    fake = FakeRedis()
    svc = RateLimitService(redis=fake)

All operations are async coroutines matching the redis.asyncio.Redis
interface. No TTL is enforced — expire() is a no-op.
"""
from __future__ import annotations


class FakeRedis:
    """
    In-memory Redis substitute covering string ops and sorted-set ops.

    String store  (_strings) : handles get / set / setex / incr / delete
    Sorted-set store (_zsets) : handles zadd / zcard / zrange / zremrangebyscore
    """

    def __init__(self) -> None:
        self._strings: dict[str, str] = {}
        self._zsets: dict[str, dict[str, float]] = {}  # {key: {member: score}}
        self._hashes: dict[str, dict[str, str]] = {}  # {key: {field: value}}

    # ── String operations ─────────────────────────────────────────────────────

    async def set(self, key: str, value: str) -> None:
        self._strings[key] = str(value)

    async def setex(self, key: str, expire_seconds: int, value: str) -> None:
        self._strings[key] = str(value)

    async def get(self, key: str) -> str | None:
        return self._strings.get(key)

    async def incr(self, key: str) -> int:
        current = int(self._strings.get(key, "0"))
        self._strings[key] = str(current + 1)
        return current + 1

    async def delete(self, *keys: str) -> int:
        removed = 0
        for k in keys:
            if k in self._strings:
                del self._strings[k]
                removed += 1
            if k in self._zsets:
                del self._zsets[k]
                removed += 1
        return removed

    # ── Sorted-set operations ─────────────────────────────────────────────────

    async def zadd(self, key: str, mapping: dict[str, float]) -> int:
        if key not in self._zsets:
            self._zsets[key] = {}
        added = sum(1 for m in mapping if m not in self._zsets[key])
        self._zsets[key].update(mapping)
        return added

    async def zcard(self, key: str) -> int:
        return len(self._zsets.get(key, {}))

    async def zrange(
        self,
        key: str,
        start: int,
        stop: int,
        withscores: bool = False,
    ) -> list:
        zset = self._zsets.get(key, {})
        ordered = sorted(zset.items(), key=lambda x: x[1])
        end = None if stop == -1 else stop + 1
        sliced = ordered[start:end]
        if withscores:
            return [(m, s) for m, s in sliced]
        return [m for m, _ in sliced]

    async def zremrangebyscore(
        self, key: str, min_score: float, max_score: float
    ) -> int:
        if key not in self._zsets:
            return 0
        to_remove = [
            m for m, s in self._zsets[key].items()
            if min_score <= s <= max_score
        ]
        for m in to_remove:
            del self._zsets[key][m]
        return len(to_remove)

    # ── Hash operations ───────────────────────────────────────────────────────

    async def hset(self, key: str, field: str | None = None, value: str | None = None, mapping: dict | None = None) -> int:
        if key not in self._hashes:
            self._hashes[key] = {}
        added = 0
        if mapping:
            for f, v in mapping.items():
                if f not in self._hashes[key]:
                    added += 1
                self._hashes[key][f] = str(v)
        elif field is not None and value is not None:
            if field not in self._hashes[key]:
                added += 1
            self._hashes[key][field] = str(value)
        return added

    async def hget(self, key: str, field: str) -> str | None:
        return self._hashes.get(key, {}).get(field)

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self._hashes.get(key, {}))

    async def hincrby(self, key: str, field: str, amount: int) -> int:
        if key not in self._hashes:
            self._hashes[key] = {}
        current = int(self._hashes[key].get(field, "0"))
        new_val = current + amount
        self._hashes[key][field] = str(new_val)
        return new_val

    async def hincrbyfloat(self, key: str, field: str, amount: float) -> float:
        if key not in self._hashes:
            self._hashes[key] = {}
        current = float(self._hashes[key].get(field, "0"))
        new_val = current + amount
        self._hashes[key][field] = str(new_val)
        return new_val

    # ── Float increment ───────────────────────────────────────────────────────

    async def incrbyfloat(self, key: str, amount: float) -> float:
        current = float(self._strings.get(key, "0"))
        new_val = current + amount
        self._strings[key] = str(new_val)
        return new_val

    # ── Key pattern matching ──────────────────────────────────────────────────

    async def keys(self, pattern: str = "*") -> list[str]:
        import fnmatch
        all_keys = list(self._strings.keys()) + list(self._zsets.keys()) + list(self._hashes.keys())
        seen = set()
        result = []
        for k in all_keys:
            if k not in seen and fnmatch.fnmatch(k, pattern):
                seen.add(k)
                result.append(k)
        return result

    # ── Pipeline ──────────────────────────────────────────────────────────────

    def pipeline(self, transaction: bool = True) -> "FakePipeline":
        return FakePipeline(self)

    # ── TTL (no-op — no real expiry in tests) ─────────────────────────────────

    async def expire(self, key: str, seconds: int) -> bool:
        return True

    # ── Connection ────────────────────────────────────────────────────────────

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        pass


class FakePipeline:
    """
    Buffered pipeline — queues commands and executes them atomically on execute().
    Supports the same subset of ops as FakeRedis.
    """

    def __init__(self, redis: FakeRedis) -> None:
        self._redis = redis
        self._queue: list = []

    def hincrby(self, key: str, field: str, amount: int) -> "FakePipeline":
        self._queue.append(("hincrby", key, field, amount))
        return self

    def hincrbyfloat(self, key: str, field: str, amount: float) -> "FakePipeline":
        self._queue.append(("hincrbyfloat", key, field, amount))
        return self

    def hset(self, key: str, field: str, value: str) -> "FakePipeline":
        self._queue.append(("hset", key, field, value))
        return self

    def incr(self, key: str) -> "FakePipeline":
        self._queue.append(("incr", key))
        return self

    def incrbyfloat(self, key: str, amount: float) -> "FakePipeline":
        self._queue.append(("incrbyfloat", key, amount))
        return self

    def set(self, key: str, value: str) -> "FakePipeline":
        self._queue.append(("set", key, value))
        return self

    def expire(self, key: str, seconds: int) -> "FakePipeline":
        self._queue.append(("expire", key, seconds))
        return self

    async def execute(self) -> list:
        results = []
        for cmd, *args in self._queue:
            fn = getattr(self._redis, cmd)
            results.append(await fn(*args))
        self._queue.clear()
        return results

    async def __aenter__(self) -> "FakePipeline":
        return self

    async def __aexit__(self, *_) -> None:
        pass
