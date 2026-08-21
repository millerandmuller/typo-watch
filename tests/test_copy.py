from squatwatch.copy import replay_label, sandbox_label, scanned_label, watch_diff_line


def test_replay_label_formats_iso_timestamp_per_section_5_spec():
    """examiner_report.md Round 1, P2: fixed verbatim format is
    'YYYY-MM-DD HH:MM UTC', not a raw ISO-8601 string."""
    assert (
        replay_label("2026-08-20T14:25:57.123456Z")
        == "Replayed from 2026-08-20 14:25 UTC. Live mode: remove ?replay=1."
    )


def test_replay_label_handles_pre_fix_seed_files_without_microseconds():
    assert (
        replay_label("2026-08-20T14:25:57Z")
        == "Replayed from 2026-08-20 14:25 UTC. Live mode: remove ?replay=1."
    )


def test_sandbox_label_states_the_shared_price():
    assert sandbox_label(12.99) == "Sandbox registration (name.com test environment). Production price: $12.99/yr."


def test_sandbox_label_omits_price_when_batch_is_mixed():
    """examiner_report.md Round 2, P3: the shared header banner used to
    silently state the FIRST card's price even when a batch mixed
    prices across TLDs/candidates -- each item's own line already shows
    its own price (_defend_result.html); the header must not claim a
    single figure it can't back up."""
    assert sandbox_label(None) == "Sandbox registration (name.com test environment)."


def test_scanned_label_formats_iso_timestamp_per_replay_label_spec():
    """A7 (project_brief.md Section 9c): live results get their own
    human-formatted timestamp, same fixed format as replay_label, never
    the raw ISO-8601 string."""
    assert scanned_label("2026-08-20T14:25:57.123456Z") == "Scanned 2026-08-20 14:25 UTC."


def test_scanned_label_handles_seed_files_without_microseconds():
    assert scanned_label("2026-08-20T14:25:57Z") == "Scanned 2026-08-20 14:25 UTC."


def _diff(since, reg, fwd, free):
    return {
        "since": since,
        "new_registrations": ["x"] * reg,
        "now_forwards_to_you": ["y"] * fwd,
        "newly_free": ["z"] * free,
    }


def test_watch_diff_line_matches_the_recorded_example_exactly():
    """A7 acceptance: 'Since 14 Aug 2026: 2 new registrations, 0 now
    forward to you, 0 newly free.' -- the exact sentence recorded in
    project_brief.md Section 9c A7."""
    diff = _diff("2026-08-14T00:00:00Z", reg=2, fwd=0, free=0)
    assert watch_diff_line(diff) == "Since 14 Aug 2026: 2 new registrations, 0 now forward to you, 0 newly free."


def test_watch_diff_line_singular_registration():
    diff = _diff("2026-08-14T00:00:00Z", reg=1, fwd=0, free=0)
    assert watch_diff_line(diff) == "Since 14 Aug 2026: 1 new registration, 0 now forward to you, 0 newly free."


def test_watch_diff_line_singular_forwards_agrees_with_verb_not_noun():
    diff = _diff("2026-08-14T00:00:00Z", reg=0, fwd=1, free=0)
    assert watch_diff_line(diff) == "Since 14 Aug 2026: 0 new registrations, 1 now forwards to you, 0 newly free."


def test_watch_diff_line_plural_forwards_at_more_than_one():
    diff = _diff("2026-08-14T00:00:00Z", reg=0, fwd=3, free=0)
    assert watch_diff_line(diff) == "Since 14 Aug 2026: 0 new registrations, 3 now forward to you, 0 newly free."


def test_watch_diff_line_never_leaks_the_raw_iso_since_string():
    diff = _diff("2026-08-14T00:00:00.987654Z", reg=1, fwd=1, free=1)
    line = watch_diff_line(diff)
    assert "2026-08-14T00:00:00" not in line
    assert line.startswith("Since 14 Aug 2026:")


def test_watch_diff_line_degrades_gracefully_on_a_malformed_since_string():
    """Round 4 adversarial re-review (examiner_report.md): this call was
    previously unguarded and raised an uncaught ValueError on a malformed
    `since` -- it must degrade the same way scanned_label/replay_label
    already do, not crash the page render."""
    diff = _diff("not-a-date-at-all", reg=2, fwd=0, free=0)
    line = watch_diff_line(diff)
    assert line == "Since not-a-date-at-all: 2 new registrations, 0 now forward to you, 0 newly free."
