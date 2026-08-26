"""A7 (project_brief.md Section 9c): `/r/{brand}` must pass the same
`_watch_diff_for(result)` the live scan routes use, not a hardcoded
`None` -- a permalink of a watched brand's latest scan should show the
same "Since <date>: N new registrations..." line the live page just
showed.

`_watch_diff_for` treats a SNAPSHOT_FROZEN_BRANDS brand as watched by
default (squatwatch/app.py) -- no manual POST /watch required, and its
diff always comes from the two committed seed snapshots in
seed/devnetwork.com/, never from live scan history. The
`_isolated_store` fixture below pins BOTH pieces of state these tests
depend on: a brand-new, empty SQLite DB (so no leftover `watch`/scan row
in the workspace's data/squatwatch.db can carry the test) AND a settings
object with devnetwork.com in `snapshot_frozen_brands` (so the test does
not silently depend on SNAPSHOT_FROZEN_BRANDS from a developer's .env --
a fresh clone has neither data/ nor .env, and this suite must pass
there; the gap was found 2026-08-26 by the first fresh-clone run without
.env). Uses the real app against the real seed files via TestClient,
same pattern as test_replay_plan_b.py.
"""

import dataclasses

import pytest
from starlette.testclient import TestClient

from squatwatch import app as app_module
from squatwatch.app import app
from squatwatch.store import Store

client = TestClient(app)

# The two seed snapshots committed at seed/devnetwork.com/*.json --
# asserted against directly so the "no raw ISO timestamp leaks" checks
# stay meaningful regardless of what (if anything) has since been
# written to data/squatwatch.db in this workspace.
_OLDER_SEED_SCANNED_AT = "2026-08-14T09:00:00Z"
_NEWER_SEED_SCANNED_AT = "2026-08-21T02:34:55.664879Z"


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    """Pin the two pieces of ambient state these tests depend on.

    Store: redirect squatwatch.app's module-level `_store` to a fresh,
    empty SQLite DB under tmp_path (same committed seed/ dir) so the
    tests can't pass on a leftover `watch`/scan row in the workspace's
    data/squatwatch.db -- a fresh clone starts with no `data/` at all.

    Settings: swap in a settings object (frozen dataclasses, hence
    `dataclasses.replace`) whose `snapshot_frozen_brands` contains
    devnetwork.com, so the frozen-brand default is asserted by the test
    itself and not inherited from SNAPSHOT_FROZEN_BRANDS in a
    developer's .env -- a fresh clone has no .env either."""
    pinned = dataclasses.replace(
        app_module._settings,
        app=dataclasses.replace(
            app_module._settings.app,
            snapshot_frozen_brands=frozenset({"devnetwork.com"}),
        ),
    )
    monkeypatch.setattr(app_module, "_settings", pinned)
    fresh_store = Store(str(tmp_path / "fresh.db"), pinned.app.seed_dir)
    monkeypatch.setattr(app_module, "_store", fresh_store)


def test_permalink_of_watched_brand_shows_the_diff_line_not_none():
    resp = client.get("/r/devnetwork.com")
    assert resp.status_code == 200
    assert "Since " in resp.text
    assert "newly free." in resp.text
    # never the raw ISO timestamp leaking into the diff's "since" clause
    assert _OLDER_SEED_SCANNED_AT not in resp.text
    assert "T09-00-00Z" not in resp.text  # nor the filename-safe form


def test_permalink_of_watched_brand_shows_the_scanned_label_not_raw_iso():
    resp = client.get("/r/devnetwork.com")
    assert resp.status_code == 200
    assert "Scanned 20" in resp.text  # "Scanned 2026-08-21 ... UTC."
    assert _NEWER_SEED_SCANNED_AT not in resp.text
