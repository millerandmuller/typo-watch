"""T-02 (project_brief.md dossier): RDAP parsing correctness."""

import httpx
import pytest
import respx

from squatwatch.cache import Cache
from squatwatch.rdap import RdapBootstrap, RdapClient

BOOTSTRAP_BODY = {
    "services": [
        [["com"], ["https://rdap.verisign.com/com/v1/"]],
        [["kg"], ["http://rdap.cctld.kg/"]],
    ]
}

GOOGLE_RDAP_BODY = {
    "objectClassName": "domain",
    "ldhName": "GOOGLE.COM",
    "entities": [
        {
            "objectClassName": "entity",
            "roles": ["registrar"],
            "vcardArray": ["vcard", [["version", {}, "text", "4.0"], ["fn", {}, "text", "MarkMonitor Inc."]]],
            "entities": [
                {
                    "objectClassName": "entity",
                    "roles": ["abuse"],
                    "vcardArray": [
                        "vcard",
                        [
                            ["version", {}, "text", "4.0"],
                            ["email", {}, "text", "abusecomplaints@markmonitor.com"],
                        ],
                    ],
                }
            ],
        }
    ],
    "events": [
        {"eventAction": "registration", "eventDate": "1997-09-15T04:00:00Z"},
        {"eventAction": "expiration", "eventDate": "2028-09-14T04:00:00Z"},
    ],
    "nameservers": [
        {"objectClassName": "nameserver", "ldhName": "NS1.GOOGLE.COM"},
        {"objectClassName": "nameserver", "ldhName": "NS2.GOOGLE.COM"},
    ],
}


@pytest.fixture
def cache(tmp_path):
    return Cache(str(tmp_path / "test.db"))


@pytest.mark.asyncio
@respx.mock
async def test_rdap_200_parses_registrar_nameservers_created_abuse(cache):
    respx.get("https://data.iana.org/rdap/dns.json").mock(
        return_value=httpx.Response(200, json=BOOTSTRAP_BODY)
    )
    respx.get("https://rdap.verisign.com/com/v1/domain/google.com").mock(
        return_value=httpx.Response(200, json=GOOGLE_RDAP_BODY)
    )
    async with httpx.AsyncClient() as client:
        bootstrap = RdapBootstrap("https://data.iana.org/rdap/dns.json", client)
        rdap_client = RdapClient(bootstrap, cache, client)
        result = await rdap_client.lookup("google.com", "com")

    assert result.registered is True
    assert result.authoritative is True
    assert result.info.registrar == "MarkMonitor Inc."
    assert result.info.abuse_email == "abusecomplaints@markmonitor.com"
    assert result.info.created == "1997-09-15T04:00:00Z"
    assert result.info.nameservers == ["ns1.google.com", "ns2.google.com"]


@pytest.mark.asyncio
@respx.mock
async def test_rdap_404_means_not_registered(cache):
    respx.get("https://data.iana.org/rdap/dns.json").mock(
        return_value=httpx.Response(200, json=BOOTSTRAP_BODY)
    )
    respx.get("https://rdap.verisign.com/com/v1/domain/zzzznotreal.com").mock(
        return_value=httpx.Response(404, json={"errorCode": 404})
    )
    async with httpx.AsyncClient() as client:
        bootstrap = RdapBootstrap("https://data.iana.org/rdap/dns.json", client)
        rdap_client = RdapClient(bootstrap, cache, client)
        result = await rdap_client.lookup("zzzznotreal.com", "com")

    assert result.registered is False
    assert result.authoritative is True


@pytest.mark.asyncio
@respx.mock
async def test_cctld_without_bootstrap_entry_is_non_authoritative(cache):
    respx.get("https://data.iana.org/rdap/dns.json").mock(
        return_value=httpx.Response(200, json=BOOTSTRAP_BODY)
    )
    async with httpx.AsyncClient() as client:
        bootstrap = RdapBootstrap("https://data.iana.org/rdap/dns.json", client)
        rdap_client = RdapClient(bootstrap, cache, client)
        result = await rdap_client.lookup("shop.de", "de")

    assert result.authoritative is False
    assert result.registered is None


@pytest.mark.asyncio
@respx.mock
async def test_rdap_result_is_cached(cache):
    respx.get("https://data.iana.org/rdap/dns.json").mock(
        return_value=httpx.Response(200, json=BOOTSTRAP_BODY)
    )
    route = respx.get("https://rdap.verisign.com/com/v1/domain/google.com").mock(
        return_value=httpx.Response(200, json=GOOGLE_RDAP_BODY)
    )
    async with httpx.AsyncClient() as client:
        bootstrap = RdapBootstrap("https://data.iana.org/rdap/dns.json", client)
        rdap_client = RdapClient(bootstrap, cache, client)
        await rdap_client.lookup("google.com", "com")
        await rdap_client.lookup("google.com", "com")

    assert route.call_count == 1  # second lookup served from cache
