import json

import httpx
import pytest
import respx

from squatwatch.cache import Cache
from squatwatch.config import NamecomConfig
from squatwatch.defend import defend
from squatwatch.models import Availability, Card

DOH_URL = "https://cloudflare-dns.com/dns-query"


@pytest.fixture
def cache(tmp_path):
    return Cache(str(tmp_path / "c.db"))


@pytest.fixture
def cfg():
    return NamecomConfig(
        sandbox_username="u-test",
        sandbox_token="tok",
        sandbox_base_url="https://api.dev.name.com",
    )


def _mock_check_availability(domain, price):
    return respx.post("https://api.dev.name.com/core/v1/domains:checkAvailability").mock(
        return_value=httpx.Response(
            200,
            json={"results": [{"domainName": domain, "purchasable": True, "purchasePrice": price}]},
        )
    )


@pytest.mark.asyncio
@respx.mock
async def test_defend_registers_and_forwards(cache, cfg):
    _mock_check_availability("ab-login.com", 12.99)
    respx.post("https://api.dev.name.com/core/v1/domains").mock(
        return_value=httpx.Response(200, json={"domain": {"domainName": "ab-login.com"}, "order": 1, "totalPaid": 12.99})
    )
    respx.post("https://api.dev.name.com/core/v1/domains/ab-login.com/url/forwarding").mock(
        return_value=httpx.Response(200, json={"id": 1, "host": "", "domainName": "ab-login.com", "forwardsTo": "https://ab.com", "type": "redirect"})
    )

    cards = [Card(domain="ab-login.com", cls="combosquat")]
    async with httpx.AsyncClient() as client:
        results = await defend(cards, "ab.com", cfg, cache, client, DOH_URL)

    assert results[0].status == "ok"
    assert results[0].pointed_home_via == "forwarding"


@pytest.mark.asyncio
@respx.mock
async def test_defend_prices_register_from_a_fresh_sandbox_quote_not_the_scan_price(cache, cfg):
    """A1 (creative_review.md Round 1): discovered live, only possible once
    NAMECOM_SANDBOX_TOKEN was unblocked (name.com ticket #3065367) --
    every prior test mocked POST /core/v1/domains to return 200
    regardless of body, so two real bugs were invisible until a real
    authenticated call hit them: (1) defend() never sent purchasePrice
    at all, and (2) even once it did, reusing card.availability.price
    (quoted by the orchestrator's PRODUCTION client during the scan)
    against the SANDBOX register call fails live with "Purchase price
    does not match" -- sandbox pricing is its own, separate quote. This
    test gives the card a stale/production price (99.00) distinct from
    the sandbox's live quote (12.99) and asserts register() is called
    with the sandbox figure, not the card's."""
    _mock_check_availability("ab-login.com", 12.99)
    register_route = respx.post("https://api.dev.name.com/core/v1/domains").mock(
        return_value=httpx.Response(200, json={"domain": {"domainName": "ab-login.com"}, "order": 1, "totalPaid": 12.99})
    )
    respx.post("https://api.dev.name.com/core/v1/domains/ab-login.com/url/forwarding").mock(
        return_value=httpx.Response(200, json={"id": 1, "host": "", "domainName": "ab-login.com", "forwardsTo": "https://ab.com", "type": "redirect"})
    )

    cards = [Card(domain="ab-login.com", cls="combosquat", availability=Availability(price=99.00))]
    async with httpx.AsyncClient() as client:
        results = await defend(cards, "ab.com", cfg, cache, client, DOH_URL)

    assert results[0].status == "ok"
    sent_body = json.loads(register_route.calls[0].request.content)
    assert sent_body["purchasePrice"] == 12.99
    # production_price on the result still reflects what the scan showed
    # the user (F8's "what this costs in production" line) -- only the
    # value sent to the sandbox register call changes.
    assert results[0].production_price == 99.00


@pytest.mark.asyncio
@respx.mock
async def test_defend_falls_back_to_a_record_when_forwarding_unavailable(cache, cfg):
    _mock_check_availability("ab-login.com", 12.99)
    respx.post("https://api.dev.name.com/core/v1/domains").mock(
        return_value=httpx.Response(200, json={"domain": {"domainName": "ab-login.com"}, "order": 1, "totalPaid": 12.99})
    )
    respx.post("https://api.dev.name.com/core/v1/domains/ab-login.com/url/forwarding").mock(
        return_value=httpx.Response(400, json={"message": "not supported in sandbox", "details": ""})
    )
    respx.get(DOH_URL, params={"name": "ab.com", "type": "A"}).mock(
        return_value=httpx.Response(200, json={"Status": 0, "Answer": [{"type": 1, "data": "203.0.113.9"}]})
    )
    respx.post("https://api.dev.name.com/core/v1/domains/ab-login.com/records").mock(
        return_value=httpx.Response(200, json={"id": 2, "type": "A", "host": "@", "answer": "203.0.113.9", "ttl": 300, "domainName": "ab-login.com"})
    )

    cards = [Card(domain="ab-login.com", cls="combosquat")]
    async with httpx.AsyncClient() as client:
        results = await defend(cards, "ab.com", cfg, cache, client, DOH_URL)

    assert results[0].status == "ok"
    assert results[0].pointed_home_via == "a-record"


@pytest.mark.asyncio
@respx.mock
async def test_defend_reports_failure_without_crash_when_registration_fails(cache, cfg):
    _mock_check_availability("ab-login.watch", 12.99)
    respx.post("https://api.dev.name.com/core/v1/domains").mock(
        return_value=httpx.Response(400, json={"message": "TLD not available in sandbox", "details": ""})
    )

    cards = [Card(domain="ab-login.watch", cls="tld-swap")]
    async with httpx.AsyncClient() as client:
        results = await defend(cards, "ab.com", cfg, cache, client, DOH_URL)

    assert results[0].status == "failed"
    assert "TLD not available" in results[0].error


@pytest.mark.asyncio
@respx.mock
async def test_defend_reports_failure_without_crash_when_price_check_fails(cache, cfg):
    respx.post("https://api.dev.name.com/core/v1/domains:checkAvailability").mock(
        return_value=httpx.Response(500, json={"message": "internal error", "details": ""})
    )

    cards = [Card(domain="ab-login.com", cls="combosquat")]
    async with httpx.AsyncClient() as client:
        results = await defend(cards, "ab.com", cfg, cache, client, DOH_URL)

    assert results[0].status == "failed"
    assert "internal error" in results[0].error
