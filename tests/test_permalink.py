"""A7 (project_brief.md Section 9c): `/r/{brand}` must pass the same
`_watch_diff_for(result)` the live scan routes use, not a hardcoded
`None` -- a permalink of a watched brand's latest scan should show the
same "Since <date>: N new registrations..." line the live page just
showed.

devnetwork.com is listed in SNAPSHOT_FROZEN_BRANDS (.env), so
`_watch_diff_for` now treats it as watched by default (squatwatch/app.py)
-- no manual POST /watch required, and its diff always comes from the
two committed seed snapshots in seed/devnetwork.com/, never from live
scan history. The `_isolated_store` fixture below points the app at a
brand-new, empty SQLite DB for each test (real seed/ directory kept), so
these tests prove that frozen-brand default on its own -- not on a
`watch` row left over from manual testing in the workspace's
data/squatwatch.db. Uses the real app against the real seed files via
TestClient, same pattern as test_replay_plan_b.py.
"""

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
    """Redirect squatwatch.app's module-level `_store` to a fresh, empty
    SQLite DB under tmp_path (same committed seed/ dir) so these tests
    can't accidentally pass only because devnetwork.com already has a
    `watch` row (or live scan rows) in the workspace's
    data/squatwatch.db -- a fresh clone starts with no `data/` at all."""
    fresh_store = Store(str(tmp_path / "fresh.db"), app_module._settings.app.seed_dir)
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
