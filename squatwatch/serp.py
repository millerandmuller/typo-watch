"""F5 — SerpApi live-in-search badge.

`site:<candidate>` Google search, capped at SERPAPI_MAX_QUERIES_PER_SCAN
per scan (default 10; per-scan QuotaTracker, not global — the cap
protects the monthly SerpApi allowance one scan at a time) and cached
24h (F12). API errors, an exhausted per-scan cap, an exhausted SerpApi
account, and a missing key all degrade to SearchInfo.checked = False
rather than blocking the band render (edge case #4), distinguished by
SearchInfo.reason ("cap" / "quota" / "error" / "no_key") for the UI
copy — "cap" is the routine, expected case (more strangers than the
per-scan budget); "quota" is reserved for the account genuinely running
out (Round 3 Creative Director finding: these two were previously
conflated into one "quota" reason, so "search quota exhausted" was
shown even when the account had 935 searches left).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

import httpx

from squatwatch.cache import Cache, get_semaphore
from squatwatch.models import SearchInfo

logger = logging.getLogger(__name__)

SERPAPI_CONCURRENCY = 5
SERPAPI_ACCOUNT_URL = "https://serpapi.com/account.json"
SERPAPI_TIMEOUT_SECONDS = 8.0

# SerpApi's documented shape for a genuine zero-organic-results answer:
# HTTP 200, this exact `error` string, no `organic_results` key. That's a
# real "checked, nothing there" answer, not an API failure — must not
# collapse into the same `checked=False` bucket as a timeout or a bad key
# (A2, creative_review.md Round 1: this is the difference between "checked,
# confirmed clean" and "search not checked" on the flagship Reveal card).
_ZERO_RESULTS_ERROR = "Google hasn't returned any results for this query."

# SerpApi's documented shape for the account genuinely running out of
# searches (https://serpapi.com/api-status-and-error-codes, verified
# 2026-08-20): HTTP 429, this exact `error` string. Checked on both the
# status code and this string since either could theoretically appear
# alone depending on how a given deployment surfaces it.
_ACCOUNT_EXHAUSTED_ERROR = "Your account has run out of searches."


def _log_search_error(domain: str, started_at: float, detail: str) -> None:
    """One WARNING per genuine search error (A2) -- class or HTTP status,
    elapsed seconds, domain. Never the API key."""
    logger.warning(
        "serpapi search failed for %s after %.1fs: %s",
        domain, time.monotonic() - started_at, detail,
    )


@dataclass
class QuotaTracker:
    max_queries: int
    used: int = 0

    def try_reserve(self) -> bool:
        if self.used >= self.max_queries:
            return False
        self.used += 1
        return True


async def live_in_search(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    domain: str,
    cache: Cache,
    quota: QuotaTracker,
) -> SearchInfo:
    if not api_key:
        return SearchInfo(checked=False, reason="no_key")

    cache_key = f"serp:{domain}"
    cached = cache.get(cache_key)
    if cached is not None:
        return SearchInfo(**cached)

    if not quota.try_reserve():
        return SearchInfo(checked=False, reason="cap")

    sem = get_semaphore("serpapi", SERPAPI_CONCURRENCY)
    params = {"engine": "google", "q": f"site:{domain}", "num": 3, "api_key": api_key}
    started_at = time.monotonic()

    resp = None
    for attempt in range(2):  # one retry on timeout (A2)
        try:
            async with sem:
                resp = await client.get(base_url, params=params, timeout=SERPAPI_TIMEOUT_SECONDS)
            break
        except httpx.TimeoutException as exc:
            if attempt == 1:
                _log_search_error(domain, started_at, type(exc).__name__)
                return SearchInfo(checked=False, reason="error")
        except httpx.TransportError as exc:
            _log_search_error(domain, started_at, type(exc).__name__)
            return SearchInfo(checked=False, reason="error")

    if resp.status_code == 429:
        return SearchInfo(checked=False, reason="quota")
    if resp.status_code != 200:
        _log_search_error(domain, started_at, f"HTTP {resp.status_code}")
        return SearchInfo(checked=False, reason="error")

    try:
        body = resp.json()
    except ValueError as exc:
        _log_search_error(domain, started_at, type(exc).__name__)
        return SearchInfo(checked=False, reason="error")

    error = body.get("error")
    if error == _ACCOUNT_EXHAUSTED_ERROR:
        return SearchInfo(checked=False, reason="quota")
    if error and error != _ZERO_RESULTS_ERROR:
        _log_search_error(domain, started_at, "error body")
        return SearchInfo(checked=False, reason="error")

    organic = body.get("organic_results", [])
    result = SearchInfo(
        checked=True,
        appears=bool(organic),
        first_title=organic[0].get("title") if organic else None,
    )
    cache.set(cache_key, result.model_dump())
    return result


async def searches_left(
    client: httpx.AsyncClient,
    api_key: str,
    cache: Cache,
) -> Optional[dict]:
    """SerpApi `/account.json`, cached 1h. Called only from the
    /methodology page (A1) — never from the scan path, so a slow or
    failing account lookup can't block or count against a scan.
    """
    if not api_key:
        return None

    async def _fetch() -> dict:
        resp = await client.get(
            SERPAPI_ACCOUNT_URL, params={"api_key": api_key}, timeout=6.0
        )
        resp.raise_for_status()
        body = resp.json()
        return {
            "plan_searches_left": body.get("plan_searches_left"),
            "searches_per_month": body.get("searches_per_month"),
        }

    try:
        value, _hit = await cache.cached_call("serp:account", _fetch, ttl_seconds=3600)
        return value
    except (httpx.HTTPError, ValueError):
        return None
