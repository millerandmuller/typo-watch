"""A3 (project_brief.md Section 9b): the free band collapses to the top
ten full cards, with the remainder inside a native <details> that still
posts to /defend. Rendered directly through Jinja2 (not the FastAPI
TestClient) so this stays a fast, isolated unit test of the template's
slicing logic — same templates/ directory Jinja2Templates(directory=...)
in squatwatch.app points at.
"""

from jinja2 import Environment, FileSystemLoader

from squatwatch.models import Band, Card, ScanResult, ScoreBreakdown, SearchInfo

_env = Environment(loader=FileSystemLoader("templates"))


def _free_card(i: int) -> Card:
    return Card(domain=f"free{i}.example.com", cls="omission", band=Band.FREE, reason="test reason")


def _render(free_count: int) -> str:
    scan = ScanResult(
        brand="example.com",
        scanned_at="2026-08-20T00:00:00Z",
        cards=[_free_card(i) for i in range(free_count)],
    )
    template = _env.get_template("_bands.html")
    return template.render(scan=scan, watch_diff=None, defensive_domains=set())


def test_free_band_over_ten_shows_details_with_correct_remainder_count():
    html = _render(23)
    assert "and 13 more, available to register today" in html


def test_free_band_of_exactly_ten_has_no_details_expander():
    html = _render(10)
    assert "more, available to register today" not in html


def test_free_band_under_ten_has_no_details_expander():
    html = _render(4)
    assert "more, available to register today" not in html


def test_free_band_over_ten_keeps_every_card_in_the_dom():
    """The rest are collapsed, not dropped — the `<details>` still posts
    to /defend, so every checkbox must remain in the form."""
    html = _render(23)
    for i in range(23):
        assert f"free{i}.example.com" in html


def test_free_band_over_ten_first_ten_render_before_the_details_tag():
    html = _render(23)
    details_index = html.index("<details")
    for i in range(10):
        assert html.index(f"free{i}.example.com") < details_index
    for i in range(10, 23):
        assert html.index(f"free{i}.example.com") > details_index


def test_raw_response_and_score_popovers_respect_the_column_width():
    """A4 (project_brief.md Section 9c), consolidated by Round 5 (Section
    9d): the score popover, raw-response popover, and draft-notice link
    are now ONE evidence <details> per row (summary "RDAP · score N")
    instead of three separate entry points. Its wrapper and the
    raw-response <pre> keep the A4 wrap-safety classes so a long JSON
    blob can't blow out the layout on a 900px-wide viewport (Round 3
    Creative Director finding)."""
    scan = ScanResult(
        brand="example.com",
        scanned_at="2026-08-20T00:00:00Z",
        cards=[Card(domain="stranger.example.com", cls="omission", band=Band.STRANGERS, reason="test reason")],
    )
    html = _env.get_template("_bands.html").render(scan=scan, watch_diff=None, defensive_domains=set())

    assert "RDAP &middot; score 0" in html
    pre_start = html.index("<pre")
    pre_tag = html[pre_start:html.index(">", pre_start)]
    assert "whitespace-pre-wrap" in pre_tag
    assert "break-words" in pre_tag
    assert "min-w-0" in pre_tag

    # the single evidence wrapper must be block/w-full/min-w-0, not
    # inline-block, so it can't widen the row past the viewport -- and
    # it's the only <details> on the page for this one-card scan, proof
    # there's one entry point, not three
    assert 'class="lg-evidence-cell block w-full min-w-0"' in html
    assert html.count("<details") == 1


def test_bands_sections_get_red_green_amber_band_colours():
    """A6 (project_brief.md Section 9c), superseded by Round 5 (Section
    9d): band identity now comes from coloured count-sentence numbers and
    a coloured verdict marker per row -- red circle (strangers), green
    circle (forward-to-you), amber square (free) -- instead of a left
    border + header tint, with the narration text unchanged."""
    scan = ScanResult(
        brand="example.com",
        scanned_at="2026-08-20T00:00:00Z",
        cards=[
            Card(domain="s1.com", cls="omission", band=Band.STRANGERS, reason="r"),
            Card(domain="y1.com", cls="omission", band=Band.YOURS),
            Card(domain="f1.com", cls="omission", band=Band.FREE, reason="r"),
        ],
    )
    html = _env.get_template("_bands.html").render(scan=scan, watch_diff=None, defensive_domains=set())

    assert '<span class="lg-num lg-num-red">1</span>' in html
    assert '<span class="lg-num lg-num-green">1</span>' in html
    assert '<span class="lg-num lg-num-amber">1</span>' in html
    assert 'lg-marker-circle lg-red' in html
    assert 'lg-marker-circle lg-green' in html
    assert 'lg-marker-square' in html

    # narration untouched by the colour change
    assert "Strangers hold 1" in html
    assert "Forward to you 1" in html
    assert "Free and dangerous 1" in html


def test_search_badge_renders_all_four_reason_strings():
    """A2 (project_brief.md Section 9c): four distinct rendered strings
    for the four SearchInfo.reason values -- "cap" (the routine per-scan
    budget case, honest about N) is now distinct from "quota" (the
    SerpApi account itself exhausted)."""

    def _render_one(search):
        scan = ScanResult(
            brand="example.com",
            scanned_at="2026-08-20T00:00:00Z",
            cards=[Card(domain="s1.com", cls="omission", band=Band.STRANGERS, reason="r", search=search)],
        )
        return _env.get_template("_bands.html").render(
            scan=scan, watch_diff=None, defensive_domains=set(), serpapi_max_queries=7
        )

    assert "not searched (7 per scan)" in _render_one(SearchInfo(checked=False, reason="cap"))
    assert "search quota exhausted" in _render_one(SearchInfo(checked=False, reason="quota"))
    assert "search not configured" in _render_one(SearchInfo(checked=False, reason="no_key"))
    assert "search not checked" in _render_one(SearchInfo(checked=False, reason="error"))


def test_search_badge_renders_the_checked_clean_state_distinctly():
    """A4 (project_brief.md Section 9e, Praktiker consult logged in
    expert_consultations.md): a searched-and-clean card (checked=True,
    appears=False) used to render NO chip at all. It must now render
    exactly its own state -- distinct from "appears" and from every
    "not searched" reason string -- so SerpApi's negative answer is
    visible in the same panel, not just in the raw JSON."""

    def _render_one(search):
        scan = ScanResult(
            brand="example.com",
            scanned_at="2026-08-20T00:00:00Z",
            cards=[Card(domain="s1.com", cls="omission", band=Band.STRANGERS, reason="r", search=search)],
        )
        return _env.get_template("_bands.html").render(
            scan=scan, watch_diff=None, defensive_domains=set(), serpapi_max_queries=10
        )

    # the "appears in Google —" CHIP is distinct from the always-present
    # "appears in Google: +N" score-breakdown line -- assert on the chip's
    # em-dash form, not the plain substring, so this test isn't tripped up
    # by the unrelated breakdown line that renders on every card.
    checked_clean_html = _render_one(SearchInfo(checked=True, appears=False))
    assert "checked against Google &mdash; does not appear" in checked_clean_html
    assert "appears in Google &mdash;" not in checked_clean_html
    assert "not searched" not in checked_clean_html

    checked_appears_html = _render_one(SearchInfo(checked=True, appears=True, first_title="Example"))
    assert "checked against Google &mdash; does not appear" not in checked_appears_html
    assert "appears in Google &mdash; &ldquo;Example&rdquo;" in checked_appears_html

    not_searched_html = _render_one(SearchInfo(checked=False, reason="cap"))
    assert "checked against Google &mdash; does not appear" not in not_searched_html
    assert "appears in Google &mdash;" not in not_searched_html


def test_free_band_header_count_unaffected_by_the_collapse():
    html = _render(23)
    assert "Free and dangerous 23" in html


def test_established_line_renders_only_when_the_component_is_non_zero():
    """A2 (project_brief.md Section 9e): the evidence panel's breakdown
    list must show "established, likely unrelated: -3" for a demoted
    card and omit the line entirely otherwise -- the six always-shown
    lines plus this conditional one must sum to the displayed total."""

    def _render_one(score):
        scan = ScanResult(
            brand="example.com",
            scanned_at="2026-08-20T00:00:00Z",
            cards=[Card(domain="s1.com", cls="omission", band=Band.STRANGERS, reason="r", score=score)],
        )
        return _env.get_template("_bands.html").render(scan=scan, watch_diff=None, defensive_domains=set())

    demoted_html = _render_one(
        ScoreBreakdown(keyword=0, mx=0, search=0, confusable=2, recent=0, parked=0, established=-3, total=-1)
    )
    assert "established, likely unrelated: -3" in demoted_html
    assert "RDAP &middot; score -1" in demoted_html

    untouched_html = _render_one(
        ScoreBreakdown(keyword=0, mx=3, search=0, confusable=0, recent=1, parked=0, established=0, total=4)
    )
    assert "established, likely unrelated" not in untouched_html
    assert "RDAP &middot; score 4" in untouched_html


def test_free_band_of_exactly_eleven_shows_the_details_boundary():
    """Adversarial re-review, Round 3: the existing suite jumped from
    n=10 straight to n=23, leaving the n=11 boundary (the first count
    where the expander must appear) implicitly-but-not-explicitly
    tested."""
    html = _render(11)
    assert "and 1 more, available to register today" in html
