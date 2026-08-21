"""Craft the "earlier" half of a seed brand's two-snapshot watch-mode
pair (D, F10 — both explicitly [GEMOCKT/KURATIERT] in project_brief.md
Section 3). Takes the one real live snapshot already on disk and writes
a second, earlier-timestamped snapshot where two currently stranger-held
cards are rolled back to "free" (as if scanned before they were
registered), so squatwatch.store.diff_snapshots has a real diff to show
("2 new registrations since ...").

The NEWER snapshot (the real live scan) is never modified — every band,
badge and fact the demo shows as current is what the live scan actually
returned on 2026-08-20. Only the OLDER snapshot is synthetic, and only
for two cards; this is the curation the brief's honesty boundary
explicitly allows (replayed/curated data must carry its own label,
which the app already does via copy.replay_label — it must never claim
to be something it isn't).

Usage: python3 scripts/curate_watch_diff.py <brand>
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from squatwatch import rank
from squatwatch.models import Band, ProbeInfo, ScanResult
from squatwatch.reason import _deterministic_reason
from squatwatch.store import Store


def craft_older_snapshot(latest: ScanResult, older_timestamp: str) -> ScanResult:
    """Only ever rolls a card BACK toward "free" in the older snapshot —
    never forward. The newer (latest, real) snapshot is never touched,
    so nothing here can put a badge on a card that wasn't actually
    observed live (the honesty boundary, Section 8): a forwards-home or
    stranger-held claim in the *newer* snapshot is always the real scan.
    """
    older = latest.model_copy(deep=True)
    older.scanned_at = older_timestamp

    # Pick real stranger-held cards from the (untouched) newer snapshot
    # and roll only the OLDER copy back to "free" — i.e. "these two got
    # registered sometime between the older scan and today."
    now_registered = [c for c in older.cards if c.band == Band.STRANGERS][:2]
    for card in now_registered:
        card.band = Band.FREE
        card.registered = False
        card.rdap = card.rdap.__class__()
        card.probe = ProbeInfo()
        card.search = card.search.__class__()
        card.availability.purchasable = True
        rank.score_and_band(card)
        card.reason = _deterministic_reason(card)

    return older


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    brand = sys.argv[1]
    store = Store("squatwatch.db", "seed")
    latest = store.latest_seed_snapshot(brand)
    if latest is None:
        print(f"No live seed snapshot for {brand} yet — run 'squatwatch seed {brand}' first.")
        sys.exit(1)

    older_ts = "2026-08-14T09:00:00Z"
    older = craft_older_snapshot(latest, older_ts)
    path = store.write_seed_snapshot(older)
    print(f"wrote curated earlier snapshot: {path}")


if __name__ == "__main__":
    main()
