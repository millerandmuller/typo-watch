import httpx
import pytest
import respx

from squatwatch.cache import Cache
from squatwatch.config import SerpapiConfig
from squatwatch.serp import SERPAPI_ACCOUNT_URL, QuotaTracker, live_in_search, searches_left

BASE_URL = "https://serpapi.com/search"


@pytest.fixture
def cache(tmp_path):
    return Cache(str(tmp_path / "cache.db"))


@pytest.mark.asyncio
@respx.mock
async def test_zero_results_maps_to_checked_true_appears_false(cache):
    """A2 (creative_review.md Round 1): SerpApi's documented zero-organic
    response is HTTP 200 with this exact `error` string and no
    `organic_results` key — a genuine "checked, nothing there" answer,
    not an API failure."""
    respx.get(BASE_URL).mock(
        return_value=httpx.Response(
            200,
            json={"error": "Google hasn't returned any results for this query."},
        )
    )
    async with httpx.AsyncClient() as client:
        info = await live_in_search(
            client, BASE_URL, "fake-key", "drvnetwork.com", cache, QuotaTracker(25)
        )
    assert info.checked is True
    assert info.appears is False
    assert info.first_title is None


@pytest.mark.asyncio
@respx.mock
async def test_genuine_error_body_still_maps_to_checked_false(cache):
    respx.get(BASE_URL).mock(
        return_value=httpx.Response(200, json={"error": "Invalid API key."})
    )
    async with httpx.AsyncClient() as client:
        info = await live_in_search(
            client, BASE_URL, "fake-key", "narne.com", cache, QuotaTracker(25)
        )
    assert info.checked is False
    assert info.reason == "error"


@pytest.mark.asyncio
@respx.mock
async def test_non_200_status_still_maps_to_checked_false(cache):
    respx.get(BASE_URL).mock(return_value=httpx.Response(500))
    async with httpx.AsyncClient() as client:
        info = await live_in_search(
            client, BASE_URL, "fake-key", "narne.com", cache, QuotaTracker(25)
        )
    assert info.checked is False
    assert info.reason == "error"


@pytest.mark.asyncio
async def test_missing_api_key_maps_to_reason_no_key(cache):
    """A1 (project_brief.md Section 9b): a missing key must render as
    "search not configured", distinct from a live check that failed."""
    async with httpx.AsyncClient() as client:
        info = await live_in_search(
            client, BASE_URL, "", "narne.com", cache, QuotaTracker(25)
        )
    assert info.checked is False
    assert info.reason == "no_key"


@pytest.mark.asyncio
async def test_exhausted_per_scan_cap_maps_to_reason_cap(cache):
    """A2 (project_brief.md Section 9c): the per-scan cap, once spent,
    renders as "not searched (N per scan)" via reason "cap" -- distinct
    from "quota", which A2 now reserves for the SerpApi ACCOUNT actually
    running out (Round 3 CD finding: these were previously conflated, so
    a routine per-scan cap showed "search quota exhausted" even with
    935 real searches left on the account)."""
    spent_quota = QuotaTracker(max_queries=1, used=1)
    async with httpx.AsyncClient() as client:
        info = await live_in_search(
            client, BASE_URL, "fake-key", "narne.com", cache, spent_quota
        )
    assert info.checked is False
    assert info.reason == "cap"


@pytest.mark.asyncio
@respx.mock
async def test_account_exhausted_429_maps_to_reason_quota(cache):
    """A2: a genuine SerpApi account exhaustion (HTTP 429, documented
    error body) is the only case that gets reason "quota" now."""
    respx.get(BASE_URL).mock(
        return_value=httpx.Response(
            429, json={"error": "Your account has run out of searches."}
        )
    )
    async with httpx.AsyncClient() as client:
        info = await live_in_search(
            client, BASE_URL, "fake-key", "narne.com", cache, QuotaTracker(25)
        )
    assert info.checked is False
    assert info.reason == "quota"


@pytest.mark.asyncio
@respx.mock
async def test_account_exhausted_body_without_429_still_maps_to_reason_quota(cache):
    """Defensive: the documented exhaustion string is recognized even if
    a deployment ever surfaces it as HTTP 200."""
    respx.get(BASE_URL).mock(
        return_value=httpx.Response(
            200, json={"error": "Your account has run out of searches."}
        )
    )
    async with httpx.AsyncClient() as client:
        info = await live_in_search(
            client, BASE_URL, "fake-key", "narne.com", cache, QuotaTracker(25)
        )
    assert info.checked is False
    assert info.reason == "quota"


@pytest.mark.asyncio
@respx.mock
async def test_timeout_then_success_retries_once(cache):
    """A2: one retry on timeout -- a transient timeout on the first
    attempt must not be treated as a permanent failure if the retry
    succeeds."""
    route = respx.get(BASE_URL).mock(
        side_effect=[
            httpx.TimeoutException("timed out"),
            httpx.Response(200, json={"organic_results": [{"title": "Example"}]}),
        ]
    )
    async with httpx.AsyncClient() as client:
        info = await live_in_search(
            client, BASE_URL, "fake-key", "narne.com", cache, QuotaTracker(25)
        )
    assert route.call_count == 2
    assert info.checked is True
    assert info.appears is True


@pytest.mark.asyncio
@respx.mock
async def test_timeout_twice_gives_up_after_one_retry(cache):
    """A2: exactly one retry -- a second consecutive timeout is a real
    failure, not retried again."""
    route = respx.get(BASE_URL).mock(side_effect=httpx.TimeoutException("timed out"))
    async with httpx.AsyncClient() as client:
        info = await live_in_search(
            client, BASE_URL, "fake-key", "narne.com", cache, QuotaTracker(25)
        )
    assert route.call_count == 2
    assert info.checked is False
    assert info.reason == "error"


@pytest.mark.asyncio
@respx.mock
async def test_search_error_logs_one_warning_without_the_api_key(cache, caplog):
    """A2: one WARNING per genuine error, with the domain and elapsed
    time but never the API key."""
    respx.get(BASE_URL).mock(return_value=httpx.Response(500))
    async with httpx.AsyncClient() as client:
        with caplog.at_level("WARNING", logger="squatwatch.serp"):
            await live_in_search(
                client, BASE_URL, "super-secret-key", "narne.com", cache, QuotaTracker(25)
            )
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert "narne.com" in warnings[0].message
    assert "super-secret-key" not in warnings[0].message


def test_default_max_queries_per_scan_is_ten(monkeypatch):
    """A1: the per-scan cap was lowered from 25 to 10 so one paid SerpApi
    month covers both recording and judging."""
    monkeypatch.delenv("SERPAPI_MAX_QUERIES_PER_SCAN", raising=False)
    assert SerpapiConfig().max_queries_per_scan == 10


@pytest.mark.asyncio
@respx.mock
async def test_searches_left_returns_plan_fields(cache):
    respx.get(SERPAPI_ACCOUNT_URL).mock(
        return_value=httpx.Response(
            200, json={"plan_searches_left": 991, "searches_per_month": 1000}
        )
    )
    async with httpx.AsyncClient() as client:
        account = await searches_left(client, "fake-key", cache)
    assert account == {"plan_searches_left": 991, "searches_per_month": 1000}


@pytest.mark.asyncio
async def test_searches_left_returns_none_without_a_key(cache):
    async with httpx.AsyncClient() as client:
        account = await searches_left(client, "", cache)
    assert account is None


@pytest.mark.asyncio
@respx.mock
async def test_searches_left_is_cached_for_an_hour(cache):
    """A1: the /methodology account lookup must not hit SerpApi on every
    page view — cached_call with ttl_seconds=3600 backs this."""
    route = respx.get(SERPAPI_ACCOUNT_URL).mock(
        return_value=httpx.Response(
            200, json={"plan_searches_left": 500, "searches_per_month": 1000}
        )
    )
    async with httpx.AsyncClient() as client:
        await searches_left(client, "fake-key", cache)
        await searches_left(client, "fake-key", cache)
    assert route.call_count == 1
