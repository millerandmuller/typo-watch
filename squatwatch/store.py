"""Scan persistence, watch-mode snapshots and diff (D), and seed/replay
snapshot files (F10).

Section 6: "SQLite via sqlite3 for scans, snapshots and cache" plus
"JSON files for seed snapshots committed to the repo
(seed/<brand>/<timestamp>.json)". D's diff is computed from two stored
snapshots, never typed by hand (D acceptance).
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from squatwatch.models import Band, ScanResult


class Store:
    def __init__(self, db_path: str, seed_dir: str = "seed"):
        self.db_path = db_path
        self.seed_dir = Path(seed_dir)
        parent = Path(db_path).parent
        if str(parent):
            parent.mkdir(parents=True, exist_ok=True)
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
                CREATE TABLE IF NOT EXISTS scans (
                    brand TEXT NOT NULL,
                    scanned_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (brand, scanned_at)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS watch (
                    brand TEXT PRIMARY KEY,
                    watching INTEGER NOT NULL DEFAULT 1
                )
                """
            )

    def save_scan(self, scan: ScanResult) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO scans (brand, scanned_at, payload) VALUES (?, ?, ?)",
                (scan.brand, scan.scanned_at, scan.model_dump_json()),
            )

    def get_latest_scan(self, brand: str) -> Optional[ScanResult]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT payload FROM scans WHERE brand = ? ORDER BY scanned_at DESC LIMIT 1",
                (brand,),
            ).fetchone()
        return ScanResult.model_validate_json(row[0]) if row else None

    def list_snapshots(self, brand: str) -> list[ScanResult]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT payload FROM scans WHERE brand = ? ORDER BY scanned_at ASC",
                (brand,),
            ).fetchall()
        return [ScanResult.model_validate_json(r[0]) for r in rows]

    def set_watch(self, brand: str, watching: bool = True) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO watch (brand, watching) VALUES (?, ?)",
                (brand, int(watching)),
            )

    def is_watched(self, brand: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT watching FROM watch WHERE brand = ?", (brand,)
            ).fetchone()
        return bool(row and row[0])

    def load_seed_snapshot(self, brand: str, timestamp: str) -> Optional[ScanResult]:
        path = self.seed_dir / brand / f"{timestamp}.json"
        if not path.exists():
            return None
        return ScanResult.model_validate_json(path.read_text())

    def latest_seed_snapshot(self, brand: str) -> Optional[ScanResult]:
        brand_dir = self.seed_dir / brand
        if not brand_dir.exists():
            return None
        files = sorted(brand_dir.glob("*.json"))
        if not files:
            return None
        return ScanResult.model_validate_json(files[-1].read_text())

    def seed_snapshots(self, brand: str) -> list[ScanResult]:
        brand_dir = self.seed_dir / brand
        if not brand_dir.exists():
            return []
        files = sorted(brand_dir.glob("*.json"))
        return [ScanResult.model_validate_json(f.read_text()) for f in files]

    def write_seed_snapshot(self, scan: ScanResult) -> Path:
        brand_dir = self.seed_dir / scan.brand
        brand_dir.mkdir(parents=True, exist_ok=True)
        safe_ts = scan.scanned_at.replace(":", "-")
        path = brand_dir / f"{safe_ts}.json"
        path.write_text(scan.model_dump_json(indent=2))
        return path

    def snapshots_for_diff(
        self,
        brand: str,
        exclude_scanned_at: Optional[str] = None,
        frozen_brands: frozenset[str] = frozenset(),
    ) -> list[ScanResult]:
        """Oldest-first snapshots for the watch-mode diff (D).

        Prefers live SQLite scan history; falls back to (or is topped up
        by) the committed curated seed snapshots when live history alone
        has fewer than two entries. Without this, the two seed snapshots
        built specifically for this feature
        (scripts/curate_watch_diff.py) are never read on a fresh clone
        or a freshly-deployed instance with no prior live scans yet —
        the exact gap examiner_report.md Round 1 flagged as P1.

        `exclude_scanned_at`: the caller's own just-completed scan is
        already persisted (orchestrator.scan calls store.save_scan
        before returning) by the time it asks for a diff to show
        alongside it. Excluding that scan's own timestamp here means
        the diff always compares two PRIOR points, not "this view
        against itself" — otherwise, live-scanning a freshly-watched
        brand even once always outranks the curated seed pair and
        silently replaces its demo story with a same-instant,
        nothing-changed diff (creative_review.md Round 1, C1 — found
        live during Round 2).

        `frozen_brands` (B1, project_brief.md Section 9c): a brand
        listed here always diffs the committed seed pair, ignoring live
        rows entirely, no matter how many exist -- `save_scan` still
        writes them (notice/Defend keep reading the live scan via
        `get_latest_scan`), only the watch-diff story for this one
        curated demo brand stays pinned to "Since 14 Aug 2026: ..." so a
        rehearsal scan can't silently overwrite it (the exact
        recurring-pollution pattern from Round 2 and Round 3).
        """
        if brand in frozen_brands:
            return self.seed_snapshots(brand)
        live = [s for s in self.list_snapshots(brand) if s.scanned_at != exclude_scanned_at]
        if len(live) >= 2:
            return live
        by_timestamp = {
            s.scanned_at: s
            for s in self.seed_snapshots(brand)
            if s.scanned_at != exclude_scanned_at
        }
        for s in live:
            by_timestamp[s.scanned_at] = s
        return sorted(by_timestamp.values(), key=lambda s: s.scanned_at)


def diff_snapshots(older: ScanResult, newer: ScanResult) -> dict:
    """D — watch-mode diff. Computed from two snapshots, never typed."""
    older_by_domain = {c.domain: c for c in older.cards}
    newer_by_domain = {c.domain: c for c in newer.cards}

    new_registrations = [
        d
        for d, c in newer_by_domain.items()
        if c.band in (Band.STRANGERS, Band.YOURS)
        and (d not in older_by_domain or older_by_domain[d].band == Band.FREE)
    ]
    now_forwards_to_you = [
        d
        for d, c in newer_by_domain.items()
        if c.band == Band.YOURS
        and (d not in older_by_domain or older_by_domain[d].band != Band.YOURS)
    ]
    newly_free = [
        d
        for d, c in newer_by_domain.items()
        if c.band == Band.FREE
        and d in older_by_domain
        and older_by_domain[d].band != Band.FREE
    ]

    return {
        "since": older.scanned_at,
        "new_registrations": new_registrations,
        "now_forwards_to_you": now_forwards_to_you,
        "newly_free": newly_free,
    }
