"""A7 (project_brief.md Section 9c): `/r/{brand}` must pass the same
`_watch_diff_for(result)` the live scan routes use, not a hardcoded
`None` -- a permalink of a watched brand's latest scan should show the
same "Since <date>: N new registrations..." line the live page just
showed. Uses the real app against the project's seeded demo brand
(devnetwork.com, watched, 3 snapshots on disk) via TestClient, same
pattern as test_replay_plan_b.py.
"""

from starlette.testclient import TestClient

from squatwatch.app import app

client = TestClient(app)


def test_permalink_of_watched_brand_shows_the_diff_line_not_none():
    resp = client.get("/r/devnetwork.com")
    assert resp.status_code == 200
    assert "Since " in resp.text
    assert "newly free." in resp.text
    # never the raw ISO timestamp leaking into the diff's "since" clause
    assert "T09-00-00Z" not in resp.text
    assert "T09:00:00" not in resp.text


def test_permalink_of_watched_brand_shows_the_scanned_label_not_raw_iso():
    resp = client.get("/r/devnetwork.com")
    assert resp.status_code == 200
    assert "Scanned 20" in resp.text  # "Scanned 2026-08-20 ... UTC."
    assert "T21:17:51" not in resp.text
