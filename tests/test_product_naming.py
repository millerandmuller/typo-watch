"""A6 (project_brief.md Section 9b): every jury-visible string says
`typo.watch`, never `squat.watch`. Checked by rendering the actual
templates through Jinja2 (same templates/ directory squatwatch.app
points at), not by grepping source — a grep would also flag the
intentionally-unchanged Python package name and the README's factual
`squat.watch → typo.watch` registration-cascade history.
"""

from jinja2 import Environment, FileSystemLoader

from squatwatch.models import ScanResult

_env = Environment(loader=FileSystemLoader("templates"))


def _render(name, **context):
    return _env.get_template(name).render(**context)


def test_landing_page_title_and_og_say_typo_watch():
    html = _render("index.html", initial=False)
    assert "typo.watch" in html
    assert "squat.watch" not in html


def test_permalink_page_title_says_typo_watch():
    scan = ScanResult(brand="example.com", scanned_at="2026-08-20T00:00:00Z", cards=[])
    html = _render("index.html", initial=True, scan=scan, watch_diff=None, defensive_domains=set())
    assert "typo.watch" in html
    assert "squat.watch" not in html


def test_methodology_page_title_says_typo_watch():
    html = _render(
        "methodology.html",
        serpapi_max_queries=10,
        namecom_budget_used=0,
        serpapi_account=None,
    )
    assert "typo.watch" in html
    assert "squat.watch" not in html


def test_404_page_title_says_typo_watch():
    html = _render("404.html")
    assert "typo.watch" in html
    assert "squat.watch" not in html
