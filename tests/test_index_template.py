"""A5 (project_brief.md Section 9b): exactly one cold-open sentence under
the input, absent once a scan result or permalink is showing. Rendered
directly through Jinja2, same templates/ directory squatwatch.app points
at.
"""

from jinja2 import Environment, FileSystemLoader

from squatwatch.models import ScanResult

_env = Environment(loader=FileSystemLoader("templates"))
_COLD_OPEN_LINE = (
    "Type your brand, see who already owns your typos, take the dangerous ones back in one click."
)


def _render(initial: bool, scan=None):
    template = _env.get_template("index.html")
    context = {"initial": initial}
    if scan is not None:
        context.update(scan=scan, watch_diff=None, defensive_domains=set())
    return template.render(**context)


def test_cold_open_sentence_present_on_the_empty_landing_page():
    html = _render(initial=False)
    assert _COLD_OPEN_LINE in html


def test_cold_open_sentence_absent_on_the_permalink_page():
    scan = ScanResult(brand="example.com", scanned_at="2026-08-20T00:00:00Z", cards=[])
    html = _render(initial=True, scan=scan)
    assert _COLD_OPEN_LINE not in html
