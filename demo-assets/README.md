# Demo assets

## vision-beat-planb-sandbox-defend.jpg

Vision beat Plan-B asset (project_brief.md Section 9, item A1).

`NAMECOM_SANDBOX_TOKEN` was blocked on name.com support ticket #3065367 through Round 1.
Confirmed unblocked 2026-08-20 via a live, read-only `checkAvailability` sandbox call.

Screenshot of a real, live "Defend (sandbox)" run against a fresh brand
(`vision-beat-planb.com`, never scanned before, so nothing here is cached or replayed):
five preselected free-band candidates registered against `api.dev.name.com`
and pointed home via URL forwarding, all under the visible
"Sandbox registration (name.com test environment)" label. Real order IDs,
real API responses — see `squatwatch/defend.py` and `tests/test_defend.py`
for the code path this exercises.

**Status: still image, not video.** The GIF/video recording tool
(`gif_creator`) reported a successful export and browser download, but the
resulting file could not be located on disk in this environment after an
extensive search (default Chrome profile, Spotlight, session scratch dirs).
Rather than ship an unverified claim, this screenshot was captured instead
via a verified, on-disk-confirmed path. Section 8's honesty boundary
applies here too: this is a real, live capture, not a mock — just a frame
instead of a clip.

**Now that the underlying bug is fixed and the flow is proven live, a
real ~10s screen recording is a five-minute task for a human with normal
screen-recording tools** (e.g. macOS `Cmd+Shift+5`): open the app, scan
any fresh, never-scanned brand, click "Defend (sandbox)", let the five
responses render. Replace this file with that recording before the actual
video shoot if higher fidelity than a still frame is wanted.

## What A1 also fixed (not just recorded)

Getting this real recording surfaced two live-only bugs in `squatwatch/defend.py`
that no mocked test had caught, because the sandbox token had never been
successfully authenticated against before:

1. `defend()` never sent `purchasePrice` to `POST /core/v1/domains` at all.
2. Once fixed, reusing `card.availability.price` (quoted by the
   orchestrator's **production** name.com client during the scan) against
   the **sandbox** register call still failed live with
   `"Purchase price does not match"` — sandbox pricing is its own,
   separate quote from production's.

Fix: `defend()` now fetches a fresh, uncached sandbox price via
`checkAvailability` immediately before each registration and prices the
purchase from that, not from the scan's (production) price. See
`squatwatch/defend.py` and the regression tests in `tests/test_defend.py`.
