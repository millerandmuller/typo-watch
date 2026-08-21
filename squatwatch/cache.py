"""F12 — quota guard: 24h cache for availability/RDAP/probe/SerpApi calls,
a global concurrency cap, and the name.com hourly budget counter shown on
the methodology page.

Backed by SQLite (project_brief.md Section 6: "SQLite via sqlite3 for
scans, snapshots and cache"). sqlite3 calls block the event loop briefly;
deliberate for a single-process hackathon build (Section 6, Architecture:
"Deliberately quick and dirty") — row counts and query cost are trivial
at this scale.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Iterator, Optional

_DEFAULT_TTL_SECONDS = 24 * 60 * 60
_semaphores: dict[str, asyncio.Semaphore] = {}


def get_semaphore(name: str, limit: int) -> asyncio.Semaphore:
    """Per-name global concurrency cap, created lazily on first use."""
    sem = _semaphores.get(name)
    if sem is None:
        sem = asyncio.Semaphore(limit)
        _semaphores[name] = sem
    return sem


class Cache:
    def __init__(self, db_path: str, default_ttl_seconds: int = _DEFAULT_TTL_SECONDS):
        self.db_path = db_path
        self.default_ttl_seconds = default_ttl_seconds
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    expires_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS namecom_budget (
                    hour_bucket TEXT PRIMARY KEY,
                    count INTEGER NOT NULL DEFAULT 0
                )
                """
            )

    def get(self, key: str) -> Any | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT value, expires_at FROM cache WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return None
        value, expires_at = row
        if expires_at < time.time():
            return None
        return json.loads(value)

    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        expires_at = time.time() + (ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds)
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO cache (key, value, expires_at) VALUES (?, ?, ?)",
                (key, json.dumps(value), expires_at),
            )

    async def cached_call(
        self,
        key: str,
        fn: Callable[[], Awaitable[Any]],
        ttl_seconds: Optional[int] = None,
    ) -> tuple[Any, bool]:
        """Return (value, was_cache_hit). Calls fn() only on a miss."""
        hit = self.get(key)
        if hit is not None:
            return hit, True
        value = await fn()
        self.set(key, value, ttl_seconds)
        return value, False

    def _current_hour_bucket(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")

    def record_namecom_call(self, n: int = 1) -> None:
        bucket = self._current_hour_bucket()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO namecom_budget (hour_bucket, count) VALUES (?, ?)
                ON CONFLICT(hour_bucket) DO UPDATE SET count = count + excluded.count
                """,
                (bucket, n),
            )

    def namecom_budget_used_this_hour(self) -> int:
        bucket = self._current_hour_bucket()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT count FROM namecom_budget WHERE hour_bucket = ?", (bucket,)
            ).fetchone()
        return row[0] if row else 0
