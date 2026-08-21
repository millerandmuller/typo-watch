"""F7 — the result page. FastAPI + Jinja2 + HTMX partials.

Route layer only: every fact-gathering decision lives in
squatwatch.orchestrator / squatwatch.rank / squatwatch.defend. This file
turns HTTP requests into calls on those modules and renders the result.
"""

from __future__ import annotations

import httpx
from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from squatwatch import copy, engine, orchestrator, serp
from squatwatch.cache import Cache
from squatwatch.config import get_settings
from squatwatch.defend import defend as run_defend
from squatwatch.store import Store, diff_snapshots

app = FastAPI(title="typo.watch")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

_settings = get_settings()
_cache = Cache(_settings.app.db_path, default_ttl_seconds=_settings.app.cache_ttl_seconds)
_store = Store(_settings.app.db_path, _settings.app.seed_dir)


def _http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Demo Plan B (project_brief.md Section 1.6): `?replay=1` on the
    homepage must actually reach the scan form, not just the backend
    `/scan/result?replay=1` endpoint — a presenter recovers from a slow
    or drifting live scan by reloading with `?replay=1` and submitting
    the same brand again, with no other code change available mid-take.
    """
    replay = bool(request.query_params.get("replay"))
    return templates.TemplateResponse(request, "index.html", {"initial": False, "replay": replay})


@app.post("/scan", response_class=HTMLResponse)
async def scan_start(request: Request, brand: str = Form(...), replay: str = Form(None)):
    try:
        parsed = engine.parse_brand(brand)
    except ValueError:
        return templates.TemplateResponse(
            request,
            "_error.html",
            {"message": "Enter a domain like your-brand.com"},
        )
    candidates, _total = engine.generate(parsed.registrable, _settings.app.max_candidates)
    return templates.TemplateResponse(
        request,
        "_progress.html",
        {
            "brand": parsed.registrable,
            "generated": len(candidates),
            "replay": bool(replay) or _settings.app.replay_default,
        },
    )


@app.get("/scan/stage", response_class=HTMLResponse)
async def scan_stage(brand: str = Query(...)):
    """B1 (creative_review.md Round 1): polled every 700ms by the
    progress line's inner span while /scan/result's own request is
    still in flight — see templates/_progress.html. Genuinely reflects
    orchestrator._scan_impl's current pipeline stage, not a fabricated
    or timer-based guess."""
    stage = orchestrator.get_stage(brand)
    return HTMLResponse(stage or "…finishing up…")


def _latest_scan_or_seed(brand: str):
    """A3 (project_brief.md Section 9c): the same seed fallback the
    permalink route already used, now shared with /notice/{domain} and
    /defend -- Plan B parity, so a scan-free demo (zero live rows) can
    still open a notice draft or reach Defend from a curated seed
    snapshot instead of failing with "Scan this brand first." """
    return _store.get_latest_scan(brand) or _store.latest_seed_snapshot(brand)


def _bands_context(result):
    """Shared `_bands.html` context (A7, project_brief.md Section 9c):
    every render site needs the same watch-diff sentence and human
    scanned-at label, computed once here instead of three times."""
    diff = _watch_diff_for(result)
    return {
        "scan": result,
        "watch_diff_line": copy.watch_diff_line(diff) if diff else None,
        "scanned_label": copy.scanned_label(result.scanned_at),
        "defensive_domains": {c.domain for c in orchestrator.top_defensive_picks(result)},
        "serpapi_max_queries": _settings.serpapi.max_queries_per_scan,
    }


def _watch_diff_for(result):
    if not _store.is_watched(result.brand):
        return None
    # Exclude this request's own just-persisted scan -- the diff shows
    # what changed BEFORE this view, not this view against itself. Only
    # for a real (non-replay) scan: replay returns an EXISTING snapshot
    # (from seed or live history) unmodified, never freshly persisted,
    # so its scanned_at can coincide with a seed file's own timestamp --
    # excluding it there would wrongly drop a real curated snapshot
    # from the pool instead of "this view" (adversarial re-review,
    # Round 2 re-review: found live via ?replay=1 on a watched brand).
    prior_snapshots = _store.snapshots_for_diff(
        result.brand,
        exclude_scanned_at=None if result.replay else result.scanned_at,
        frozen_brands=_settings.app.snapshot_frozen_brands,
    )
    if len(prior_snapshots) >= 2:
        return diff_snapshots(prior_snapshots[-2], prior_snapshots[-1])
    return None


@app.get("/scan/result", response_class=HTMLResponse)
async def scan_result(request: Request, brand: str = Query(...), replay: bool = Query(False)):
    """B1 (project_brief.md Section 9b): a replayed scan is already
    complete (cached snapshot, no external calls) and stays a single
    swap, unchanged from before. A live scan only runs through
    availability + RDAP + probe here -- swap 1 -- and returns
    `_bands_phase1.html`, whose own `hx-get` chains into `/scan/result2`
    for swap 2 (search + reasons + free band)."""
    try:
        if replay:
            async with _http_client() as client:
                result = await orchestrator.scan(
                    brand, _settings, _cache, _store, client, replay=True
                )
            return templates.TemplateResponse(request, "_bands.html", _bands_context(result))

        async with _http_client() as client:
            result = await orchestrator.scan_phase1(brand, _settings, _cache, client)
    except (ValueError, LookupError) as exc:
        return templates.TemplateResponse(
            request, "_error.html", {"message": f"Could not scan {brand}: {exc}"}
        )

    return templates.TemplateResponse(request, "_bands_phase1.html", {"scan": result})


@app.get("/scan/result2", response_class=HTMLResponse)
async def scan_result2(request: Request, brand: str = Query(...)):
    """B1 swap 2: search + reasons + final score, then the one store
    write for this live scan. Always follows a `/scan/result` (swap 1)
    call for the same brand -- see scan_phase2's docstring."""
    try:
        async with _http_client() as client:
            result = await orchestrator.scan_phase2(brand, _settings, _cache, _store, client)
    except (ValueError, LookupError) as exc:
        return templates.TemplateResponse(
            request, "_error.html", {"message": f"Could not scan {brand}: {exc}"}
        )

    return templates.TemplateResponse(request, "_bands.html", _bands_context(result))


@app.get("/r/{brand}", response_class=HTMLResponse)
async def permalink(request: Request, brand: str):
    result = _latest_scan_or_seed(brand)
    if result is None:
        return templates.TemplateResponse(request, "404.html", {}, status_code=404)
    return templates.TemplateResponse(
        request, "index.html", {"initial": True, **_bands_context(result)}
    )


@app.post("/defend", response_class=HTMLResponse)
async def defend_route(request: Request, brand: str = Form(...), domains: list[str] = Form([])):
    latest = _latest_scan_or_seed(brand)
    if latest is None:
        return templates.TemplateResponse(
            request, "_error.html", {"message": "Scan this brand first."}
        )
    cards = [c for c in latest.cards if c.domain in domains]
    if not cards:
        return templates.TemplateResponse(
            request,
            "_error.html",
            {"message": "Pick at least one domain from this scan to defend."},
        )
    async with _http_client() as client:
        results = await run_defend(
            cards, brand, _settings.namecom, _cache, client, _settings.dns.doh_resolver_url
        )
    priced = {c.availability.price for c in cards if c.availability.price is not None}
    sandbox_price = priced.pop() if len(priced) == 1 else None
    return templates.TemplateResponse(
        request,
        "_defend_result.html",
        {"results": results, "sandbox_label": copy.sandbox_label(sandbox_price)},
    )


@app.get("/notice/{domain}", response_class=HTMLResponse)
async def notice_route(request: Request, domain: str, brand: str = Query(...)):
    latest = _latest_scan_or_seed(brand)
    if latest is None:
        return templates.TemplateResponse(
            request, "_error.html", {"message": "Scan this brand first."}
        )
    try:
        draft = orchestrator.build_notice_draft(latest, domain)
    except LookupError:
        return templates.TemplateResponse(
            request, "_error.html", {"message": f"No card for {domain} in the last scan."}
        )
    except ValueError:
        return templates.TemplateResponse(
            request,
            "_error.html",
            {"message": f"{domain} is free to register — nothing to notify."},
        )
    return templates.TemplateResponse(request, "_notice.html", {"draft": draft})


@app.post("/watch")
async def watch_route(brand: str = Form(...)):
    _store.set_watch(brand, True)
    return HTMLResponse(status_code=204, content="")


@app.get("/methodology", response_class=HTMLResponse)
async def methodology(request: Request):
    serpapi_account = None
    if _settings.serpapi.api_key:
        async with _http_client() as client:
            serpapi_account = await serp.searches_left(
                client, _settings.serpapi.api_key, _cache
            )
    return templates.TemplateResponse(
        request,
        "methodology.html",
        {
            "serpapi_max_queries": _settings.serpapi.max_queries_per_scan,
            "namecom_budget_used": _cache.namecom_budget_used_this_hour(),
            "serpapi_account": serpapi_account,
            "snapshot_frozen_brands": sorted(_settings.app.snapshot_frozen_brands),
        },
    )
