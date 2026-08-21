from squatwatch.models import Band, Card, CoverageFooter, ScanResult
from squatwatch.store import Store, diff_snapshots


def _scan(brand, scanned_at, domains_bands):
    return ScanResult(
        brand=brand,
        scanned_at=scanned_at,
        cards=[Card(domain=d, cls="combosquat", band=b) for d, b in domains_bands],
        footer=CoverageFooter(generated=len(domains_bands), answered=len(domains_bands), not_authoritative=0),
    )


def test_snapshots_for_diff_falls_back_to_seed_when_live_history_is_thin(tmp_path):
    """examiner_report.md Round 1, P1: on a fresh clone/instance with no
    prior live scans, the watch-mode diff must still be able to use the
    committed curated seed snapshots — not silently produce nothing."""
    store = Store(str(tmp_path / "fresh.db"), str(tmp_path / "seed"))

    older = _scan("brand.com", "2026-08-01T00:00:00Z", [("a.com", Band.FREE)])
    newer = _scan("brand.com", "2026-08-10T00:00:00Z", [("a.com", Band.STRANGERS)])
    store.write_seed_snapshot(older)
    store.write_seed_snapshot(newer)

    assert store.list_snapshots("brand.com") == []  # no live SQLite history yet

    snaps = store.snapshots_for_diff("brand.com")
    assert len(snaps) == 2
    assert snaps[0].scanned_at == "2026-08-01T00:00:00Z"
    assert snaps[1].scanned_at == "2026-08-10T00:00:00Z"

    diff = diff_snapshots(snaps[0], snaps[1])
    assert diff["new_registrations"] == ["a.com"]


def test_snapshots_for_diff_prefers_live_history_when_sufficient(tmp_path):
    store = Store(str(tmp_path / "live.db"), str(tmp_path / "seed"))
    live_older = _scan("brand.com", "2026-08-15T00:00:00Z", [("b.com", Band.FREE)])
    live_newer = _scan("brand.com", "2026-08-16T00:00:00Z", [("b.com", Band.STRANGERS)])
    store.save_scan(live_older)
    store.save_scan(live_newer)
    # a stale/unrelated seed snapshot should not override real live history
    store.write_seed_snapshot(_scan("brand.com", "2020-01-01T00:00:00Z", [("b.com", Band.FREE)]))

    snaps = store.snapshots_for_diff("brand.com")
    assert len(snaps) == 2
    assert snaps[0].scanned_at == "2026-08-15T00:00:00Z"
    assert snaps[1].scanned_at == "2026-08-16T00:00:00Z"


def test_snapshots_for_diff_excludes_the_just_completed_scan(tmp_path):
    """C1 (creative_review.md Round 1), found live during Round 2: on a
    freshly-watched brand with zero real prior history, the ONE live
    scan that renders the current page is already persisted by the time
    the route asks for a diff -- without exclude_scanned_at, that scan
    outranks the curated seed pair and the diff silently compares
    "this view against itself" (always 0 changes) instead of showing
    the intended curated story."""
    store = Store(str(tmp_path / "fresh.db"), str(tmp_path / "seed"))
    older = _scan("brand.com", "2026-08-14T09-00-00Z", [("a.com", Band.FREE)])
    newer_seed = _scan("brand.com", "2026-08-20T14-26-12Z", [("a.com", Band.STRANGERS)])
    store.write_seed_snapshot(older)
    store.write_seed_snapshot(newer_seed)

    just_now = _scan("brand.com", "2026-08-20T19-30-00Z", [("a.com", Band.STRANGERS)])
    store.save_scan(just_now)  # what orchestrator.scan already did before this call

    snaps = store.snapshots_for_diff("brand.com", exclude_scanned_at=just_now.scanned_at)
    assert [s.scanned_at for s in snaps] == ["2026-08-14T09-00-00Z", "2026-08-20T14-26-12Z"]

    diff = diff_snapshots(snaps[0], snaps[1])
    assert diff["new_registrations"] == ["a.com"]


def test_snapshots_for_diff_exclusion_still_falls_back_correctly_with_no_seed_left(tmp_path):
    store = Store(str(tmp_path / "fresh.db"), str(tmp_path / "seed"))
    live_a = _scan("brand.com", "2026-08-15T00:00:00Z", [("b.com", Band.FREE)])
    live_b = _scan("brand.com", "2026-08-16T00:00:00Z", [("b.com", Band.STRANGERS)])
    store.save_scan(live_a)
    store.save_scan(live_b)

    snaps = store.snapshots_for_diff("brand.com", exclude_scanned_at=live_b.scanned_at)
    assert [s.scanned_at for s in snaps] == ["2026-08-15T00:00:00Z"]  # only 1 left, no diff possible


def test_snapshots_for_diff_frozen_brand_ignores_live_rows_even_with_three(tmp_path):
    """B1 (project_brief.md Section 9c): a frozen brand's watch-diff
    always compares the committed seed pair, no matter how many live
    scans have piled up since — the recurring devnetwork.com
    live-scan-pollution pattern from Round 2 and Round 3."""
    store = Store(str(tmp_path / "frozen.db"), str(tmp_path / "seed"))
    older_seed = _scan("brand.com", "2026-08-14T09:00:00Z", [("a.com", Band.FREE)])
    newer_seed = _scan("brand.com", "2026-08-20T14:26:12Z", [("a.com", Band.STRANGERS)])
    store.write_seed_snapshot(older_seed)
    store.write_seed_snapshot(newer_seed)

    for i in range(3):
        store.save_scan(_scan("brand.com", f"2026-08-2{i}T19:30:00Z", [("a.com", Band.YOURS)]))

    snaps = store.snapshots_for_diff("brand.com", frozen_brands=frozenset({"brand.com"}))
    assert [s.scanned_at for s in snaps] == ["2026-08-14T09:00:00Z", "2026-08-20T14:26:12Z"]

    diff = diff_snapshots(snaps[0], snaps[1])
    assert diff["new_registrations"] == ["a.com"]
    # the frozen brand's diff never sees the live rows' "yours" band at all
    assert diff["now_forwards_to_you"] == []


def test_snapshots_for_diff_unfrozen_brand_unaffected_by_frozen_brands_set(tmp_path):
    """A brand not in `frozen_brands` keeps the existing live-preferring
    behaviour untouched."""
    store = Store(str(tmp_path / "unfrozen.db"), str(tmp_path / "seed"))
    live_older = _scan("other.com", "2026-08-15T00:00:00Z", [("b.com", Band.FREE)])
    live_newer = _scan("other.com", "2026-08-16T00:00:00Z", [("b.com", Band.STRANGERS)])
    store.save_scan(live_older)
    store.save_scan(live_newer)

    snaps = store.snapshots_for_diff("other.com", frozen_brands=frozenset({"brand.com"}))
    assert [s.scanned_at for s in snaps] == ["2026-08-15T00:00:00Z", "2026-08-16T00:00:00Z"]
