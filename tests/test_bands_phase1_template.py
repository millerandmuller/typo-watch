"""B1 (project_brief.md Section 9b): swap 1 (_bands_phase1.html) shows
band headers with counts, the full "yours" band, and plain "strangers"
cards (domain, class, land line) — never a search badge, a reason, or
the free band's card list, even when the underlying data already has
them (a card carrying search.appears=True and a reason is exactly the
regression this guards against: the template must suppress it, not the
data pipeline). Rendered directly through Jinja2, same templates/
directory squatwatch.app points at.
"""

from jinja2 import Environment, FileSystemLoader

from squatwatch.models import Band, Card, ProbeInfo, ProbeKind, ScanResult, ScoreBreakdown, SearchInfo

_env = Environment(loader=FileSystemLoader("templates"))


def _stranger_card(domain, appears_in_search=True, with_reason=True):
    return Card(
        domain=domain,
        cls="omission",
        band=Band.STRANGERS,
        land_line="Live site titled 'Example'.",
        probe=ProbeInfo(kind=ProbeKind.LIVE_OTHER, title="Example"),
        search=SearchInfo(checked=True, appears=appears_in_search, first_title="Example — Home"),
        reason="A live site using this look-alike, found in search." if with_reason else None,
        score=ScoreBreakdown(total=5),
    )


def _yours_card(domain):
    return Card(
        domain=domain,
        cls="omission",
        band=Band.YOURS,
        land_line="Already yours. Ends on www.example.com after one redirect.",
        probe=ProbeInfo(kind=ProbeKind.FORWARDS_HOME, chain=["http://x/"], final_host="www.example.com"),
    )


def _free_card(domain):
    return Card(domain=domain, cls="omission", band=Band.FREE, reason="Available to register today.")


def _render(cards):
    scan = ScanResult(brand="example.com", scanned_at="2026-08-20T00:00:00Z", cards=cards)
    return _env.get_template("_bands_phase1.html").render(scan=scan)


def test_swap1_shows_all_three_band_headers_with_counts():
    html = _render([_stranger_card("s1.com"), _yours_card("y1.com"), _free_card("f1.com")])
    assert "Strangers hold 1" in html
    assert "Forward to you 1" in html
    assert "Free and dangerous 1" in html


def test_swap1_never_shows_a_search_badge_even_when_search_already_appears():
    html = _render([_stranger_card("s1.com", appears_in_search=True)])
    assert "appears in Google" not in html
    assert "search not checked" not in html
    assert "search quota exhausted" not in html


def test_swap1_never_shows_a_reason_even_when_one_is_already_set():
    html = _render([_stranger_card("s1.com", with_reason=True)])
    assert "A live site using this look-alike, found in search." not in html


def test_swap1_shows_plain_stranger_card_domain_class_and_land_line():
    html = _render([_stranger_card("s1.com")])
    assert "s1.com" in html
    assert "Live site titled" in html
    assert "score " not in html  # score popover suppressed too — genuinely "plain"
    assert "raw response" not in html
    assert "draft notice" not in html


def test_swap1_shows_the_full_yours_band_card():
    html = _render([_yours_card("y1.com")])
    assert "y1.com" in html
    assert "Already yours" in html
    assert "redirect chain" in html


def test_swap1_never_renders_the_free_band_card_list():
    html = _render([_free_card("f1.com")])
    assert "f1.com" not in html
    assert "defend this one" not in html


def test_swap1_chains_into_scan_result2_via_hx_get():
    html = _render([_stranger_card("s1.com")])
    assert 'hx-get="/scan/result2?brand=example.com"' in html
    assert 'hx-trigger="load"' in html


def test_swap1_bands_already_show_red_green_amber_colours():
    """A6 (project_brief.md Section 9c): swap 1 is already coloured, not
    just the final swap-2 render, since it's the first thing a live scan
    shows on stage."""
    html = _render([_stranger_card("s1.com"), _yours_card("y1.com"), _free_card("f1.com")])
    assert "border-red-600" in html
    assert "bg-red-50" in html
    assert "border-green-600" in html
    assert "bg-green-50" in html
    assert "border-amber-600" in html
    assert "bg-amber-50" in html
