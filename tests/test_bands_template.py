"""A3 (project_brief.md Section 9b): the free band collapses to the top
ten full cards, with the remainder inside a native <details> that still
posts to /defend. Rendered directly through Jinja2 (not the FastAPI
TestClient) so this stays a fast, isolated unit test of the template's
slicing logic — same templates/ directory Jinja2Templates(directory=...)
in squatwatch.app points at.
"""

from jinja2 import Environment, FileSystemLoader

from squatwatch.models import Band, Card, ScanResult, SearchInfo

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
    """A4 (project_brief.md Section 9c): the raw-response and score
    popovers must never force the page wider than its column — the
    details wrapper is block/w-full/min-w-0 and the raw-response <pre>
    wraps instead of scrolling, so a long JSON blob can't blow out the
    layout on a 900px-wide viewport (Round 3 Creative Director finding)."""
    scan = ScanResult(
        brand="example.com",
        scanned_at="2026-08-20T00:00:00Z",
        cards=[Card(domain="stranger.example.com", cls="omission", band=Band.STRANGERS, reason="test reason")],
    )
    html = _env.get_template("_bands.html").render(scan=scan, watch_diff=None, defensive_domains=set())

    assert 'raw response' in html
    pre_start = html.index("<pre")
    pre_tag = html[pre_start:html.index(">", pre_start)]
    assert "whitespace-pre-wrap" in pre_tag
    assert "break-words" in pre_tag

    # both <details> wrappers around the popovers must be block/w-full/min-w-0,
    # not inline-block, so they can't widen the flex row past the viewport
    assert 'class="block w-full min-w-0 text-sm text-slate-600"' in html
    assert "inline-block text-sm text-slate-600" not in html


def test_bands_sections_get_red_green_amber_band_colours():
    """A6 (project_brief.md Section 9c): a left border plus header tint
    per band -- red strangers, green forward-to-you, amber free -- with
    the narration text unchanged (Round 3 user rule)."""
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

    assert "border-red-600" in html
    assert "bg-red-50" in html
    assert "border-green-600" in html
    assert "bg-green-50" in html
    assert "border-amber-600" in html
    assert "bg-amber-50" in html

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


def test_free_band_header_count_unaffected_by_the_collapse():
    html = _render(23)
    assert "Free and dangerous 23" in html


def test_free_band_of_exactly_eleven_shows_the_details_boundary():
    """Adversarial re-review, Round 3: the existing suite jumped from
    n=10 straight to n=23, leaving the n=11 boundary (the first count
    where the expander must appear) implicitly-but-not-explicitly
    tested."""
    html = _render(11)
    assert "and 1 more, available to register today" in html
