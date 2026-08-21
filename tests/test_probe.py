"""T-03 (forwards-home) and T-06 (mail-only) from project_brief.md dossier."""

from datetime import datetime, timezone

import httpx
import pytest
import respx

from squatwatch.cache import Cache
from squatwatch.copy import land_line
from squatwatch.models import Card, ProbeKind, RdapInfo
from squatwatch.probe import classify
from squatwatch.rank import is_established_unrelated, score_and_band

DOH_URL = "https://cloudflare-dns.com/dns-query"


def _doh_response(status=0, answers=None):
    return httpx.Response(200, json={"Status": status, "Answer": answers or []})


@pytest.mark.asyncio
@respx.mock
async def test_forwards_home_classification_gogle_google():
    """T-03: gogle.com resolves and 301s to www.google.com (D-05, D-06)."""
    respx.get(DOH_URL, params={"name": "gogle.com", "type": "A"}).mock(
        return_value=_doh_response(answers=[{"type": 1, "data": "203.0.113.9"}])
    )
    respx.get(DOH_URL, params={"name": "gogle.com", "type": "MX"}).mock(
        return_value=_doh_response(answers=[])
    )
    respx.get(DOH_URL, params={"name": "gogle.com", "type": "NS"}).mock(
        return_value=_doh_response(answers=[{"type": 2, "data": "ns1.example-registrar.com."}])
    )
    respx.get("http://gogle.com/").mock(
        return_value=httpx.Response(301, headers={"location": "https://www.google.com/"})
    )
    respx.get("https://www.google.com/").mock(
        return_value=httpx.Response(200, content=b"<title>Google</title>")
    )

    async with httpx.AsyncClient() as client:
        info = await classify(client, DOH_URL, "gogle.com", "google.com")

    assert info.kind == ProbeKind.FORWARDS_HOME
    assert info.final_host == "www.google.com"
    assert len(info.chain) == 2


@pytest.mark.asyncio
@respx.mock
async def test_mail_only_classification():
    """T-06: MX present, no A record -> mail-only."""
    respx.get(DOH_URL, params={"name": "narne.com", "type": "A"}).mock(
        return_value=_doh_response(answers=[])
    )
    respx.get(DOH_URL, params={"name": "narne.com", "type": "MX"}).mock(
        return_value=_doh_response(answers=[{"type": 15, "data": "10 mail.narne.com."}])
    )
    respx.get(DOH_URL, params={"name": "narne.com", "type": "NS"}).mock(
        return_value=_doh_response(answers=[])
    )

    async with httpx.AsyncClient() as client:
        info = await classify(client, DOH_URL, "narne.com", "name.com")

    assert info.kind == ProbeKind.MAIL_ONLY
    assert info.mx == ["mail.narne.com"]
    assert info.a == []


@pytest.mark.asyncio
@respx.mock
async def test_dark_classification_no_records():
    respx.get(DOH_URL, params={"name": "nowhere-example.com", "type": "A"}).mock(
        return_value=_doh_response(status=3)
    )
    respx.get(DOH_URL, params={"name": "nowhere-example.com", "type": "MX"}).mock(
        return_value=_doh_response(status=3)
    )
    respx.get(DOH_URL, params={"name": "nowhere-example.com", "type": "NS"}).mock(
        return_value=_doh_response(status=3)
    )

    async with httpx.AsyncClient() as client:
        info = await classify(client, DOH_URL, "nowhere-example.com", "name.com")

    assert info.kind == ProbeKind.DARK


@pytest.mark.asyncio
@respx.mock
async def test_parked_classification_via_nameserver_marker():
    respx.get(DOH_URL, params={"name": "brnad.com", "type": "A"}).mock(
        return_value=_doh_response(answers=[{"type": 1, "data": "198.51.100.5"}])
    )
    respx.get(DOH_URL, params={"name": "brnad.com", "type": "MX"}).mock(
        return_value=_doh_response(answers=[])
    )
    respx.get(DOH_URL, params={"name": "brnad.com", "type": "NS"}).mock(
        return_value=_doh_response(answers=[{"type": 2, "data": "ns1.sedoparking.com."}])
    )
    respx.get("http://brnad.com/").mock(
        return_value=httpx.Response(200, content=b"<title>brnad.com is for sale</title>")
    )

    async with httpx.AsyncClient() as client:
        info = await classify(client, DOH_URL, "brnad.com", "name.com")

    assert info.kind == ProbeKind.PARKED


@pytest.mark.asyncio
@respx.mock
async def test_probe_result_is_cached_for_24h(tmp_path):
    """F12: a re-probe of the same domain within the cache TTL makes no
    new DoH/HTTP calls."""
    cache = Cache(str(tmp_path / "cache.db"))
    a_route = respx.get(DOH_URL, params={"name": "narne.com", "type": "A"}).mock(
        return_value=_doh_response(answers=[{"type": 1, "data": "203.0.113.5"}])
    )
    respx.get(DOH_URL, params={"name": "narne.com", "type": "MX"}).mock(return_value=_doh_response())
    respx.get(DOH_URL, params={"name": "narne.com", "type": "NS"}).mock(return_value=_doh_response())
    http_route = respx.get("http://narne.com/").mock(
        return_value=httpx.Response(200, content=b"<title>Narne</title>")
    )

    async with httpx.AsyncClient() as client:
        first = await classify(client, DOH_URL, "narne.com", "name.com", cache)
        second = await classify(client, DOH_URL, "narne.com", "name.com", cache)

    assert first == second
    assert a_route.call_count == 1
    assert http_route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_null_mx_is_not_mail_configured():
    """examiner_report.md Round 1, P1: RFC 7505 null MX ("0 .") must not
    count as mail configured — it explicitly declares no mail service."""
    respx.get(DOH_URL, params={"name": "example.com", "type": "A"}).mock(
        return_value=_doh_response(answers=[{"type": 1, "data": "203.0.113.1"}])
    )
    respx.get(DOH_URL, params={"name": "example.com", "type": "MX"}).mock(
        return_value=_doh_response(answers=[{"type": 15, "data": "0 ."}])
    )
    respx.get(DOH_URL, params={"name": "example.com", "type": "NS"}).mock(
        return_value=_doh_response(answers=[])
    )
    respx.get("http://example.com/").mock(
        return_value=httpx.Response(200, content=b"<title>Real Site</title>")
    )

    async with httpx.AsyncClient() as client:
        info = await classify(client, DOH_URL, "example.com", "brand.com")

    assert info.mx == []
    assert info.kind == ProbeKind.LIVE_OTHER


@pytest.mark.asyncio
@respx.mock
async def test_localhost_mx_is_not_mail_configured():
    """B2 (project_brief.md Section 9b; expert_consultations.md
    2026-08-20): a parking service's placeholder MX of "localhost" is not
    reachable from the public internet and must not count as mail
    configured, the same way null MX is excluded above."""
    respx.get(DOH_URL, params={"name": "example.com", "type": "A"}).mock(
        return_value=_doh_response(answers=[{"type": 1, "data": "203.0.113.1"}])
    )
    respx.get(DOH_URL, params={"name": "example.com", "type": "MX"}).mock(
        return_value=_doh_response(answers=[{"type": 15, "data": "10 localhost."}])
    )
    respx.get(DOH_URL, params={"name": "example.com", "type": "NS"}).mock(
        return_value=_doh_response(answers=[])
    )
    respx.get("http://example.com/").mock(
        return_value=httpx.Response(200, content=b"<title>Real Site</title>")
    )

    async with httpx.AsyncClient() as client:
        info = await classify(client, DOH_URL, "example.com", "brand.com")

    assert info.mx == []
    assert info.kind == ProbeKind.LIVE_OTHER


@pytest.mark.asyncio
@respx.mock
async def test_tmx_org_style_parked_domain_loses_mail_configured():
    """B2 acceptance case, live-observed on tmx.org: Sedo parking
    nameservers, probe kind=parked, MX="localhost" — must classify
    PARKED with an empty mx list, so score_and_band gives no +3 and
    draft_notice omits the MX line."""
    respx.get(DOH_URL, params={"name": "tmx.org", "type": "A"}).mock(
        return_value=_doh_response(answers=[{"type": 1, "data": "198.51.100.68"}])
    )
    respx.get(DOH_URL, params={"name": "tmx.org", "type": "MX"}).mock(
        return_value=_doh_response(answers=[{"type": 15, "data": "0 localhost."}])
    )
    respx.get(DOH_URL, params={"name": "tmx.org", "type": "NS"}).mock(
        return_value=_doh_response(answers=[{"type": 2, "data": "ns1.sedoparking.com."}])
    )
    respx.get("http://tmx.org/").mock(
        return_value=httpx.Response(200, content=b"<title>tmx.org is parked</title>")
    )

    async with httpx.AsyncClient() as client:
        info = await classify(client, DOH_URL, "tmx.org", "name.com")

    assert info.kind == ProbeKind.PARKED
    assert info.mx == []

    card = Card(domain="tmx.org", cls="replacement", registered=True, probe=info)
    scored = score_and_band(card)
    assert scored.score.mx == 0


@pytest.mark.asyncio
@respx.mock
async def test_parking_provider_zone_mx_is_not_mail_configured():
    """B2: an MX host published inside a known parking provider's own
    zone (not just "localhost") is the same non-functional placeholder,
    not a distinct interception risk."""
    respx.get(DOH_URL, params={"name": "example.com", "type": "A"}).mock(
        return_value=_doh_response(answers=[{"type": 1, "data": "203.0.113.1"}])
    )
    respx.get(DOH_URL, params={"name": "example.com", "type": "MX"}).mock(
        return_value=_doh_response(answers=[{"type": 15, "data": "10 mx.sedoparking.com."}])
    )
    respx.get(DOH_URL, params={"name": "example.com", "type": "NS"}).mock(
        return_value=_doh_response(answers=[])
    )
    respx.get("http://example.com/").mock(
        return_value=httpx.Response(200, content=b"<title>Real Site</title>")
    )

    async with httpx.AsyncClient() as client:
        info = await classify(client, DOH_URL, "example.com", "brand.com")

    assert info.mx == []


@pytest.mark.asyncio
@respx.mock
async def test_mx_host_that_merely_contains_a_parking_marker_substring_still_counts():
    """Adversarial re-review, Round 3: the parking-zone MX check must be
    suffix-aware, not a raw substring match — a real business self-
    hosting mail at "mail.riseabove.com" is not in "above.com"'s zone
    just because the marker string appears inside a longer domain label
    (live-reproduced false positive against "above.com", "voodoo.com",
    "parked.com", "bodis.com")."""
    respx.get(DOH_URL, params={"name": "example.com", "type": "A"}).mock(
        return_value=_doh_response(answers=[{"type": 1, "data": "203.0.113.1"}])
    )
    respx.get(DOH_URL, params={"name": "example.com", "type": "MX"}).mock(
        return_value=_doh_response(answers=[{"type": 15, "data": "10 mail.riseabove.com."}])
    )
    respx.get(DOH_URL, params={"name": "example.com", "type": "NS"}).mock(
        return_value=_doh_response(answers=[])
    )
    respx.get("http://example.com/").mock(
        return_value=httpx.Response(200, content=b"<title>Real Site</title>")
    )

    async with httpx.AsyncClient() as client:
        info = await classify(client, DOH_URL, "example.com", "brand.com")

    assert info.mx == ["mail.riseabove.com"]


@pytest.mark.asyncio
@respx.mock
async def test_parked_classification_via_title_marker():
    """academy-fix: a "for sale" landing page (naeee.com/namu.com-style)
    must classify as parked from the page title alone — no parking
    nameserver involved, live A record, old RDAP creation date. Before
    this fix these fell through to live-other and picked up the
    established-unrelated line downstream (rank.is_established_unrelated
    only excludes non-live-other kinds, so getting the kind right here
    is what keeps that rule from firing)."""
    respx.get(DOH_URL, params={"name": "naeee.com", "type": "A"}).mock(
        return_value=_doh_response(answers=[{"type": 1, "data": "198.51.100.20"}])
    )
    respx.get(DOH_URL, params={"name": "naeee.com", "type": "MX"}).mock(
        return_value=_doh_response(answers=[])
    )
    respx.get(DOH_URL, params={"name": "naeee.com", "type": "NS"}).mock(
        return_value=_doh_response(answers=[{"type": 2, "data": "ns1.some-registrar.com."}])
    )
    respx.get("http://naeee.com/").mock(
        return_value=httpx.Response(200, content=b"<title>Domain Name For Sale</title>")
    )

    async with httpx.AsyncClient() as client:
        info = await classify(client, DOH_URL, "naeee.com", "name.com")

    assert info.kind == ProbeKind.PARKED

    old_created = datetime(2007, 3, 1, tzinfo=timezone.utc).isoformat()
    card = score_and_band(
        Card(
            domain="naeee.com",
            cls="replacement",
            registered=True,
            probe=info,
            rdap=RdapInfo(created=old_created),
        )
    )
    assert card.score.parked == -1
    assert is_established_unrelated(card) is False
    assert land_line(card) == "Parked for sale."


@pytest.mark.asyncio
@respx.mock
async def test_a_record_present_never_falls_back_to_mail_only():
    """examiner_report.md Round 1, P1: a domain with an A record has
    web-facing infrastructure by definition — an inconclusive HTTP
    resolution must degrade to UNKNOWN, never the false claim
    "no website" (mail-only), even when MX is also present."""
    respx.get(DOH_URL, params={"name": "ambiguous.com", "type": "A"}).mock(
        return_value=_doh_response(answers=[{"type": 1, "data": "203.0.113.9"}])
    )
    respx.get(DOH_URL, params={"name": "ambiguous.com", "type": "MX"}).mock(
        return_value=_doh_response(answers=[{"type": 15, "data": "10 mail.ambiguous.com."}])
    )
    respx.get(DOH_URL, params={"name": "ambiguous.com", "type": "NS"}).mock(
        return_value=_doh_response(answers=[])
    )
    # A destination that never resolves to a clean 2xx (e.g. a 500).
    respx.get("http://ambiguous.com/").mock(return_value=httpx.Response(500))

    async with httpx.AsyncClient() as client:
        info = await classify(client, DOH_URL, "ambiguous.com", "brand.com")

    assert info.kind == ProbeKind.UNKNOWN
    assert info.mx == ["mail.ambiguous.com"]
