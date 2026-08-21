"""A3 (project_brief.md Section 9c): `/notice/{domain}` and `/defend`
must fall back to a seed snapshot when the live store has no scan for
the brand yet -- Plan B parity with the permalink route, which already
did this. Route-level tests against a temporary, empty Store (no live
scans) with one seed snapshot written directly, monkeypatched over
squatwatch.app's module-level `_store` so the real project's data/
and seed/ directories are never touched.
"""

import pytest
from starlette.testclient import TestClient

from squatwatch import app as app_module
from squatwatch.models import Band, Card, ScanResult
from squatwatch.store import Store


@pytest.fixture
def seeded_empty_store(tmp_path, monkeypatch):
    store = Store(str(tmp_path / "empty.db"), str(tmp_path / "seed"))
    scan = ScanResult(
        brand="acme-test.com",
        scanned_at="2026-08-14T09:00:00Z",
        cards=[
            Card(domain="stranger-acme-test.com", cls="omission", band=Band.STRANGERS, reason="r"),
        ],
    )
    store.write_seed_snapshot(scan)
    monkeypatch.setattr(app_module, "_store", store)
    return store


def test_notice_route_falls_back_to_seed_when_store_has_no_live_scan(seeded_empty_store):
    client = TestClient(app_module.app)
    resp = client.get("/notice/stranger-acme-test.com", params={"brand": "acme-test.com"})
    assert resp.status_code == 200
    assert "Scan this brand first" not in resp.text


def test_defend_route_falls_back_to_seed_and_reaches_run_defend(seeded_empty_store, monkeypatch):
    called = {}

    async def fake_run_defend(cards, brand, cfg, cache, client, doh_url):
        called["domains"] = [c.domain for c in cards]
        called["brand"] = brand
        return []

    monkeypatch.setattr(app_module, "run_defend", fake_run_defend)
    client = TestClient(app_module.app)
    resp = client.post(
        "/defend", data={"brand": "acme-test.com", "domains": ["stranger-acme-test.com"]}
    )
    assert resp.status_code == 200
    assert "Scan this brand first" not in resp.text
    assert called["brand"] == "acme-test.com"
    assert called["domains"] == ["stranger-acme-test.com"]


def test_notice_route_still_errors_when_neither_live_scan_nor_seed_exists(seeded_empty_store):
    """The fallback only kicks in when a seed exists -- a brand with
    genuinely no history anywhere still gets the honest "Scan this brand
    first." message, not a crash."""
    client = TestClient(app_module.app)
    resp = client.get("/notice/whatever.com", params={"brand": "never-scanned-brand.com"})
    assert resp.status_code == 200
    assert "Scan this brand first" in resp.text


def test_defend_route_still_errors_when_neither_live_scan_nor_seed_exists(seeded_empty_store):
    client = TestClient(app_module.app)
    resp = client.post(
        "/defend", data={"brand": "never-scanned-brand.com", "domains": ["whatever.com"]}
    )
    assert resp.status_code == 200
    assert "Scan this brand first" in resp.text
