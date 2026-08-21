"""Integration test for orchestrator.scan wiring every F-module together,
against recorded fixtures (respx) — no live network, no model call."""

import asyncio
from dataclasses import replace

import httpx
import pytest
import respx

from squatwatch import engine, orchestrator
from squatwatch.cache import Cache
from squatwatch.config import (
    AnthropicConfig,
    AppConfig,
    DnsConfig,
    NamecomConfig,
    Settings,
    SerpapiConfig,
)
from squatwatch.models import Band, Card, CoverageFooter, ProbeInfo, ProbeKind, ScanResult, ScoreBreakdown
from squatwatch.store import Store

DOH_URL = "https://cloudflare-dns.com/dns-query"
BOOTSTRAP_URL = "https://data.iana.org/rdap/dns.json"


def _doh(status=0, answers=None):
    return httpx.Response(200, json={"Status": status, "Answer": answers or []})


@pytest.fixture
def settings(tmp_path):
    return Settings(
        namecom=NamecomConfig(
            username="u", token="t", base_url="https://api.name.com", batch_size=50,
            rate_limit_per_second=1000,  # no throttling slowdown in tests
        ),
        serpapi=SerpapiConfig(api_key="test-key", max_queries_per_scan=25),
        anthropic=AnthropicConfig(api_key=""),  # forces deterministic fallback
        dns=DnsConfig(rdap_bootstrap_url=BOOTSTRAP_URL, doh_resolver_url=DOH_URL),
        app=AppConfig(max_candidates=6, db_path=str(tmp_path / "test.db"), seed_dir=str(tmp_path / "seed")),
    )


@pytest.fixture
def cache(tmp_path):
    return Cache(str(tmp_path / "cache.db"))


@pytest.fixture
def store(settings):
    return Store(settings.app.db_path, settings.app.seed_dir)


@pytest.mark.asyncio
@respx.mock
async def test_full_scan_pipeline(settings, cache, store):
    respx.post("https://api.name.com/core/v1/domains:checkAvailability").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {"domainName": "ab-account.com", "purchasable": True, "purchasePrice": 12.99},
                    {"domainName": "ab-billing.com", "purchasable": False},
                    {"domainName": "ab-help.com", "purchasable": False},
                    {"domainName": "ab-login.com", "purchasable": False},
                    {"domainName": "ab-mail.com", "purchasable": False},
                    # ab-pay.com deliberately omitted -> "registered": None (pending)
                ]
            },
        )
    )

    respx.post("https://api.name.com/core/v1/domains:search").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {"domainName": "ab-secure.net", "purchasable": True, "purchasePrice": 9.99},
                ]
            },
        )
    )

    respx.get(BOOTSTRAP_URL).mock(
        return_value=httpx.Response(
            200, json={"services": [[["com"], ["https://rdap.verisign.com/com/v1/"]]]}
        )
    )
    respx.get("https://rdap.verisign.com/com/v1/domain/ab-billing.com").mock(
        return_value=httpx.Response(200, json={"objectClassName": "domain"})
    )
    respx.get("https://rdap.verisign.com/com/v1/domain/ab-help.com").mock(
        return_value=httpx.Response(200, json={"objectClassName": "domain"})
    )
    respx.get("https://rdap.verisign.com/com/v1/domain/ab-login.com").mock(
        return_value=httpx.Response(200, json={"objectClassName": "domain"})
    )
    respx.get("https://rdap.verisign.com/com/v1/domain/ab-mail.com").mock(
        return_value=httpx.Response(404, json={})
    )

    # ab-billing.com: forwards-home
    respx.get(DOH_URL, params={"name": "ab-billing.com", "type": "A"}).mock(
        return_value=_doh(answers=[{"type": 1, "data": "203.0.113.1"}])
    )
    respx.get(DOH_URL, params={"name": "ab-billing.com", "type": "MX"}).mock(return_value=_doh())
    respx.get(DOH_URL, params={"name": "ab-billing.com", "type": "NS"}).mock(return_value=_doh())
    respx.get("http://ab-billing.com/").mock(
        return_value=httpx.Response(301, headers={"location": "https://www.ab.com/"})
    )
    respx.get("https://www.ab.com/").mock(return_value=httpx.Response(200, content=b"<title>AB</title>"))

    # ab-help.com: mail-only
    respx.get(DOH_URL, params={"name": "ab-help.com", "type": "A"}).mock(return_value=_doh())
    respx.get(DOH_URL, params={"name": "ab-help.com", "type": "MX"}).mock(
        return_value=_doh(answers=[{"type": 15, "data": "10 mail.ab-help.com."}])
    )
    respx.get(DOH_URL, params={"name": "ab-help.com", "type": "NS"}).mock(return_value=_doh())

    # ab-login.com: parked
    respx.get(DOH_URL, params={"name": "ab-login.com", "type": "A"}).mock(
        return_value=_doh(answers=[{"type": 1, "data": "198.51.100.4"}])
    )
    respx.get(DOH_URL, params={"name": "ab-login.com", "type": "MX"}).mock(return_value=_doh())
    respx.get(DOH_URL, params={"name": "ab-login.com", "type": "NS"}).mock(
        return_value=_doh(answers=[{"type": 2, "data": "ns1.sedoparking.com."}])
    )
    respx.get("http://ab-login.com/").mock(
        return_value=httpx.Response(200, content=b"<title>ab-login.com is for sale</title>")
    )

    # SerpApi for ab-help.com and ab-login.com (both probed, non-forwards-home)
    respx.get("https://serpapi.com/search").mock(
        return_value=httpx.Response(200, json={"organic_results": []})
    )

    async with httpx.AsyncClient() as client:
        result = await orchestrator.scan("ab.com", settings, cache, store, client, replay=False)

    by_domain = {c.domain: c for c in result.cards}
    assert len(result.cards) == 6

    assert by_domain["ab-account.com"].band == Band.FREE
    assert by_domain["ab-billing.com"].band == Band.YOURS
    assert by_domain["ab-help.com"].band == Band.STRANGERS
    assert by_domain["ab-help.com"].land_line == "Can receive your customers' email. No website."
    assert by_domain["ab-login.com"].band == Band.STRANGERS
    assert by_domain["ab-login.com"].land_line == "Parked for sale."
    assert by_domain["ab-mail.com"].band == Band.FREE  # RDAP 404 overrode a stale "registered"
    assert by_domain["ab-pay.com"].band is None  # pending, availability never answered

    assert result.footer.generated == 6
    assert result.footer.answered == 5  # everything except ab-pay.com
    assert result.slowed_down is False
    assert result.suggestions[0].domain_name == "ab-secure.net"

    # every card has a reason (deterministic fallback since anthropic key is empty)
    assert all(c.reason for c in result.cards)

    # persisted for the permalink (/r/<brand>)
    reloaded = store.get_latest_scan("ab.com")
    assert reloaded is not None
    assert reloaded.brand == "ab.com"

    # B1: the stage tracker is cleared once the scan finishes — a poll
    # arriving after completion must not show a stale in-progress message.
    assert orchestrator.get_stage("ab.com") is None


@pytest.mark.asyncio
@respx.mock
async def test_concurrent_scans_of_same_brand_are_deduped(settings, cache, store):
    """examiner_report.md Round 1, P2: N concurrent cold requests for the
    same never-scanned brand must not each run the full pipeline and
    multiply real name.com API usage by N."""
    candidate_domains = [c.domain for c in engine.generate("ab.com", 6)[0]]
    avail_route = respx.post("https://api.name.com/core/v1/domains:checkAvailability").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {"domainName": d, "purchasable": True, "purchasePrice": 4.99}
                    for d in candidate_domains
                ]
            },
        )
    )
    search_route = respx.post("https://api.name.com/core/v1/domains:search").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    respx.get(BOOTSTRAP_URL).mock(
        return_value=httpx.Response(200, json={"services": [[["com"], ["https://rdap.verisign.com/com/v1/"]]]})
    )

    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(
            *(
                orchestrator.scan("ab.com", settings, cache, store, client, replay=False)
                for _ in range(3)
            )
        )

    assert avail_route.call_count == 1  # not 3
    assert search_route.call_count == 1  # not 3
    assert all(r.brand == "ab.com" for r in results)
    assert len(store.list_snapshots("ab.com")) == 1  # not silently lost, not duplicated


@pytest.mark.asyncio
@respx.mock
async def test_stage_tracking_reflects_pipeline_progress(settings, cache, store):
    """B1 (creative_review.md Round 1): squatwatch/app.py's /scan/stage
    route polls orchestrator.get_stage(brand) — it must genuinely reflect
    which pipeline leg is in flight, not a fabricated or timer-based
    guess. Holds the RDAP call open with an asyncio.Event to observe the
    "asking the registry" stage mid-scan, then confirms it advances past
    that stage and is cleared once the scan completes."""
    candidate_domains = [c.domain for c in engine.generate("ab.com", 6)[0]]
    respx.post("https://api.name.com/core/v1/domains:checkAvailability").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {"domainName": d, "purchasable": False} for d in candidate_domains
                ]
            },
        )
    )
    respx.post("https://api.name.com/core/v1/domains:search").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    respx.get(BOOTSTRAP_URL).mock(
        return_value=httpx.Response(
            200, json={"services": [[["com"], ["https://rdap.verisign.com/com/v1/"]]]}
        )
    )

    rdap_holds = asyncio.Event()
    stage_seen_mid_rdap = None

    async def _slow_rdap(request):
        nonlocal stage_seen_mid_rdap
        stage_seen_mid_rdap = orchestrator.get_stage("ab.com")
        rdap_holds.set()
        await asyncio.sleep(0.05)
        return httpx.Response(200, json={"objectClassName": "domain"})

    for d in candidate_domains:
        respx.get(f"https://rdap.verisign.com/com/v1/domain/{d}").mock(side_effect=_slow_rdap)
        respx.get(DOH_URL, params={"name": d, "type": "A"}).mock(return_value=_doh())
        respx.get(DOH_URL, params={"name": d, "type": "MX"}).mock(return_value=_doh())
        respx.get(DOH_URL, params={"name": d, "type": "NS"}).mock(return_value=_doh())
    respx.get("https://serpapi.com/search").mock(
        return_value=httpx.Response(200, json={"organic_results": []})
    )

    async with httpx.AsyncClient() as client:
        task = asyncio.ensure_future(
            orchestrator.scan("ab.com", settings, cache, store, client, replay=False)
        )
        await asyncio.wait_for(rdap_holds.wait(), timeout=2.0)
        await task

    assert stage_seen_mid_rdap == "…asking the registry…"
    assert orchestrator.get_stage("ab.com") is None


def _mock_full_pipeline_for(candidate_domains, purchasable=True):
    """Shared respx wiring for a fresh, never-scanned brand where every
    candidate is a plain free (purchasable) domain — enough to exercise
    availability + RDAP (skipped, nothing registered) + probe (skipped)
    without per-domain fixtures. Used by the B1 phase1/phase2 tests,
    which care about dedup/staging/row-count, not per-band content."""
    avail_route = respx.post("https://api.name.com/core/v1/domains:checkAvailability").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {"domainName": d, "purchasable": purchasable, "purchasePrice": 4.99}
                    for d in candidate_domains
                ]
            },
        )
    )
    search_route = respx.post("https://api.name.com/core/v1/domains:search").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    respx.get(BOOTSTRAP_URL).mock(
        return_value=httpx.Response(
            200, json={"services": [[["com"], ["https://rdap.verisign.com/com/v1/"]]]}
        )
    )
    return avail_route, search_route


@pytest.mark.asyncio
@respx.mock
async def test_scan_phase1_gives_provisional_bands_without_search_or_reason(settings, cache):
    """B1 (project_brief.md Section 9b): swap 1's result must have real
    band counts and land lines from availability + RDAP + probe alone —
    every card's search must still be unchecked and reason unset, since
    neither has run yet."""
    candidate_domains = [c.domain for c in engine.generate("ab.com", 6)[0]]
    _mock_full_pipeline_for(candidate_domains, purchasable=False)  # all "taken" -> strangers
    for d in candidate_domains:
        respx.get(f"https://rdap.verisign.com/com/v1/domain/{d}").mock(
            return_value=httpx.Response(200, json={"objectClassName": "domain"})
        )
        respx.get(DOH_URL, params={"name": d, "type": "A"}).mock(return_value=_doh())
        respx.get(DOH_URL, params={"name": d, "type": "MX"}).mock(return_value=_doh())
        respx.get(DOH_URL, params={"name": d, "type": "NS"}).mock(return_value=_doh())

    async with httpx.AsyncClient() as client:
        result = await orchestrator.scan_phase1("ab.com", settings, cache, client)

    assert result.footer.generated == 6
    assert sum(result.band_counts().values()) == 6
    assert all(c.search.checked is False for c in result.cards)
    assert all(c.reason is None for c in result.cards)
    strangers = [c for c in result.cards if c.band == Band.STRANGERS]
    assert strangers and all(c.land_line for c in strangers)


@pytest.mark.asyncio
@respx.mock
async def test_run_phase2_searches_highest_score_candidates_first_when_capped(settings, cache, store):
    """A2 (project_brief.md Section 9c): with a per-scan cap of 3 and 5
    eligible cards at different provisional scores, only the top 3 by
    score reach SerpApi -- generation order (dict insertion order here
    is deliberately NOT score order) must not decide who gets searched.
    Ties break on domain, deterministically."""
    capped_settings = replace(settings, serpapi=replace(settings.serpapi, max_queries_per_scan=3))
    parsed = engine.parse_brand("brand.com")
    # insertion order is deliberately scrambled relative to score, so a
    # test that passed under generation-order search would fail here
    specs = [("low.com", 1), ("mid.com", 5), ("high.com", 9), ("tie-b.com", 5), ("tie-a.com", 5)]
    cards = {
        domain: Card(
            domain=domain,
            cls="omission",
            registered=True,
            probe=ProbeInfo(kind=ProbeKind.DARK),
            score=ScoreBreakdown(total=score),
        )
        for domain, score in specs
    }
    state = orchestrator._Phase1State(
        parsed=parsed, cards=cards, suggestions=[], slowed_down=False, total_before_cap=5
    )
    search_route = respx.get("https://serpapi.com/search").mock(
        return_value=httpx.Response(200, json={"organic_results": []})
    )

    async with httpx.AsyncClient() as client:
        await orchestrator._run_phase2(state, capped_settings, cache, store, client)

    assert search_route.call_count == 3
    searched = {d for d, c in cards.items() if c.search.checked}
    capped = {d for d, c in cards.items() if c.search.reason == "cap"}
    assert searched == {"high.com", "mid.com", "tie-a.com"}  # top score, then tie-break by domain
    assert capped == {"low.com", "tie-b.com"}


@pytest.mark.asyncio
@respx.mock
async def test_scan_phase2_without_phase1_raises_lookup_error(settings, cache, store):
    """B1: the HTMX flow always calls scan_phase1 first — a phase2 call
    for a brand with no completed phase1 is a client-ordering error, not
    something to silently run from scratch (that would defeat the two-
    swap design and double the registry calls)."""
    async with httpx.AsyncClient() as client:
        with pytest.raises(LookupError):
            await orchestrator.scan_phase2("never-scanned-xyz.com", settings, cache, store, client)


@pytest.mark.asyncio
@respx.mock
async def test_scan_phase1_then_phase2_writes_exactly_one_scan_row(settings, cache, store):
    """B1 acceptance: exactly one scan row per live scan — phase1 must
    not persist anything, and phase2's single store.save_scan call is
    the only write for the whole two-swap flow."""
    candidate_domains = [c.domain for c in engine.generate("ab.com", 6)[0]]
    _mock_full_pipeline_for(candidate_domains, purchasable=True)  # all free -> no RDAP/probe needed
    respx.get("https://serpapi.com/search").mock(
        return_value=httpx.Response(200, json={"organic_results": []})
    )

    async with httpx.AsyncClient() as client:
        phase1_result = await orchestrator.scan_phase1("ab.com", settings, cache, client)
        assert store.list_snapshots("ab.com") == []  # nothing persisted yet

        final_result = await orchestrator.scan_phase2("ab.com", settings, cache, store, client)

    assert len(store.list_snapshots("ab.com")) == 1
    assert final_result.brand == phase1_result.brand
    assert all(c.reason for c in final_result.cards)  # reasons now filled in


@pytest.mark.asyncio
@respx.mock
async def test_concurrent_scan_phase1_calls_are_deduped(settings, cache):
    """B1: mirrors examiner_report.md Round 1 P2's scan() dedup test —
    concurrent phase-1 requests for the same never-scanned brand must
    share one pipeline run, not multiply registry calls."""
    candidate_domains = [c.domain for c in engine.generate("ab.com", 6)[0]]
    avail_route, search_route = _mock_full_pipeline_for(candidate_domains, purchasable=True)

    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(
            *(orchestrator.scan_phase1("ab.com", settings, cache, client) for _ in range(3))
        )

    assert avail_route.call_count == 1
    assert search_route.call_count == 1
    assert all(r.brand == "ab.com" for r in results)


@pytest.mark.asyncio
@respx.mock
async def test_concurrent_scan_phase2_calls_are_deduped(settings, cache, store):
    """B1: concurrent phase-2 requests for the same brand (e.g. two
    browser tabs both mid-scan) must share one search/reason/save run,
    not write more than one scan row."""
    candidate_domains = [c.domain for c in engine.generate("ab.com", 6)[0]]
    _mock_full_pipeline_for(candidate_domains, purchasable=True)
    search_route = respx.get("https://serpapi.com/search").mock(
        return_value=httpx.Response(200, json={"organic_results": []})
    )

    async with httpx.AsyncClient() as client:
        await orchestrator.scan_phase1("ab.com", settings, cache, client)
        results = await asyncio.gather(
            *(
                orchestrator.scan_phase2("ab.com", settings, cache, store, client)
                for _ in range(3)
            )
        )

    assert all(r.brand == "ab.com" for r in results)
    assert len(store.list_snapshots("ab.com")) == 1


@pytest.mark.asyncio
@respx.mock
async def test_scan_phase2_late_arrival_after_winning_task_finished_gets_cached_result(
    settings, cache, store
):
    """Adversarial re-review, Round 3: a phase2 request arriving AFTER the
    first winning phase2 task already finished and cleaned up its
    in-flight entry must not error with "call scan_phase1 first" (live-
    reproduced: 4 of 6 genuinely concurrent /scan/result2 calls failed
    this way) or start a second pipeline run (which would violate
    "exactly one scan row per live scan") -- it must get the same
    completed result."""
    candidate_domains = [c.domain for c in engine.generate("ab.com", 6)[0]]
    avail_route, search_route = _mock_full_pipeline_for(candidate_domains, purchasable=True)

    async with httpx.AsyncClient() as client:
        await orchestrator.scan_phase1("ab.com", settings, cache, client)
        first = await orchestrator.scan_phase2("ab.com", settings, cache, store, client)
        # the winning task's own dedup entries are now cleaned up (finally
        # already ran) -- this call arrives strictly AFTER that point,
        # exactly the race the adversarial examiner reproduced live.
        late = await orchestrator.scan_phase2("ab.com", settings, cache, store, client)

    assert late.brand == first.brand
    assert late.scanned_at == first.scanned_at  # same completed result, not a new run
    assert avail_route.call_count == 1
    assert search_route.call_count == 1
    assert len(store.list_snapshots("ab.com")) == 1


@pytest.mark.asyncio
@respx.mock
async def test_scan_phase1_abandoned_then_fresh_rescan_runs_the_pipeline_again(
    settings, cache
):
    """Adversarial re-review, Round 3: if a browser abandons the page
    after phase1 (never calls scan_phase2), a LATER, genuinely fresh
    scan_phase1 call for the same brand must run the pipeline again, not
    silently replay the old abandoned state (live-reproduced: a "fresh"
    re-scan returned in 0.19s, byte-identical to the original, with zero
    new registry calls -- Principle 1's "every taken is a registry
    answer" guarantee breaks if stale data gets served, and worse,
    persisted under a fresh timestamp, as current). F12's 24h per-domain
    availability cache is a separate, correctly-working concern -- it
    can legitimately make the underlying HTTP call a cache hit on the
    second run, so the proof here is that `_run_phase1` itself executes
    a second time (patched with a call-through wrapper), not that the
    network was necessarily re-hit.
    """
    candidate_domains = [c.domain for c in engine.generate("ab.com", 6)[0]]
    _mock_full_pipeline_for(candidate_domains, purchasable=True)

    real_run_phase1 = orchestrator._run_phase1
    calls = []

    async def _spy(*args, **kwargs):
        calls.append(1)
        return await real_run_phase1(*args, **kwargs)

    async with httpx.AsyncClient() as client:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(orchestrator, "_run_phase1", _spy)
            first = await orchestrator.scan_phase1("ab.com", settings, cache, client)
            # phase2 is deliberately never called -- the abandoned-tab case
            second = await orchestrator.scan_phase1("ab.com", settings, cache, client)

    assert len(calls) == 2  # the pipeline genuinely ran again, not a cached replay
    assert second.scanned_at != first.scanned_at  # a genuinely new state, not replayed


@pytest.mark.asyncio
@respx.mock
async def test_phase1_then_phase2_stage_sequence(settings, cache, store):
    """B1 acceptance: stage-sequence — the progress line must genuinely
    advance from phase-1 stages into phase-2 stages across the two HTTP
    round trips, not jump straight to the end or reset."""
    candidate_domains = [c.domain for c in engine.generate("ab.com", 6)[0]]
    _mock_full_pipeline_for(candidate_domains, purchasable=False)
    for d in candidate_domains:
        respx.get(f"https://rdap.verisign.com/com/v1/domain/{d}").mock(
            return_value=httpx.Response(200, json={"objectClassName": "domain"})
        )
        respx.get(DOH_URL, params={"name": d, "type": "A"}).mock(return_value=_doh())
        respx.get(DOH_URL, params={"name": d, "type": "MX"}).mock(return_value=_doh())
        respx.get(DOH_URL, params={"name": d, "type": "NS"}).mock(return_value=_doh())
    respx.get("https://serpapi.com/search").mock(
        return_value=httpx.Response(200, json={"organic_results": []})
    )

    async with httpx.AsyncClient() as client:
        await orchestrator.scan_phase1("ab.com", settings, cache, client)
        stage_after_phase1 = orchestrator.get_stage("ab.com")
        await orchestrator.scan_phase2("ab.com", settings, cache, store, client)

    assert stage_after_phase1 == "…probing where they point…"
    assert orchestrator.get_stage("ab.com") is None  # cleared once phase2 finishes


@pytest.mark.asyncio
async def test_replay_mode_uses_seed_snapshot_no_network(settings, cache, store):
    from squatwatch.models import Card, CoverageFooter, ScanResult

    seed = ScanResult(
        brand="ab.com",
        scanned_at="2026-08-19T14:02:00Z",
        cards=[Card(domain="ab-billing.com", cls="combosquat", band=Band.YOURS)],
        footer=CoverageFooter(generated=1, answered=1, not_authoritative=0),
    )
    store.write_seed_snapshot(seed)

    async with httpx.AsyncClient() as client:
        result = await orchestrator.scan("ab.com", settings, cache, store, client, replay=True)

    assert result.replay is True
    assert result.replay_label is not None
    assert result.cards[0].domain == "ab-billing.com"


def test_build_notice_draft_refuses_free_band_domain():
    """examiner_report.md Round 1, P1: a UDRP-style notice must never be
    drafted for a domain nobody has registered."""
    scan = ScanResult(
        brand="ab.com",
        scanned_at="2026-08-20T00:00:00Z",
        cards=[Card(domain="ab-free.com", cls="combosquat", band=Band.FREE)],
        footer=CoverageFooter(generated=1, answered=1, not_authoritative=0),
    )
    with pytest.raises(ValueError, match="not stranger-held"):
        orchestrator.build_notice_draft(scan, "ab-free.com")


def test_build_notice_draft_allows_strangers_band_domain():
    scan = ScanResult(
        brand="ab.com",
        scanned_at="2026-08-20T00:00:00Z",
        cards=[Card(domain="ab-taken.com", cls="combosquat", band=Band.STRANGERS)],
        footer=CoverageFooter(generated=1, answered=1, not_authoritative=0),
    )
    draft = orchestrator.build_notice_draft(scan, "ab-taken.com")
    assert "ab-taken.com" in draft


def test_top_defensive_picks_excludes_premium_domains():
    """examiner_report.md Round 1, P1: premium-priced free candidates
    ($335k on a real scan) must never land in the defensive top-5 or the
    price-of-prevention sum."""
    from squatwatch.models import Availability

    cards = [
        Card(domain="cheap1.com", cls="combosquat", band=Band.FREE,
             availability=Availability(purchasable=True, price=4.99, premium=False)),
        Card(domain="premium1.com", cls="homoglyph", band=Band.FREE,
             availability=Availability(purchasable=True, price=276000.0, premium=True)),
        Card(domain="cheap2.com", cls="combosquat", band=Band.FREE,
             availability=Availability(purchasable=True, price=9.99, premium=False)),
    ]
    scan = ScanResult(
        brand="ab.com",
        scanned_at="2026-08-20T00:00:00Z",
        cards=cards,
        footer=CoverageFooter(generated=3, answered=3, not_authoritative=0),
    )
    picks = orchestrator.top_defensive_picks(scan)
    assert [c.domain for c in picks] == ["cheap1.com", "cheap2.com"]
    assert "premium1.com" not in [c.domain for c in picks]


def test_price_of_prevention_excludes_missing_prices_from_sum():
    """examiner_report.md re-review, Round 1, P2: a missing price must
    not be silently counted as $0 — 3 of 5 real google.com picks had
    "price pending" and the sum looked complete but wasn't."""
    from squatwatch.models import Availability

    top5 = [
        Card(domain="a.com", cls="combosquat", band=Band.FREE,
             availability=Availability(purchasable=True, price=4.99)),
        Card(domain="b.com", cls="combosquat", band=Band.FREE,
             availability=Availability(purchasable=True, price=None)),  # price pending
        Card(domain="c.com", cls="combosquat", band=Band.FREE,
             availability=Availability(purchasable=True, price=9.99)),
    ]
    prices = orchestrator._price_of_prevention(top5)
    assert prices.top5_sum == 14.98  # only a.com + c.com, not 0 for b.com
    assert prices.top5_priced_count == 2
    assert prices.top5_total_count == 3


def test_price_of_prevention_all_unpriced_gives_no_sum():
    from squatwatch.models import Availability

    top5 = [
        Card(domain="a.com", cls="combosquat", band=Band.FREE,
             availability=Availability(purchasable=True, price=None)),
    ]
    prices = orchestrator._price_of_prevention(top5)
    assert prices.top5_sum is None
