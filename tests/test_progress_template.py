"""Demo-Rehearsal finding, Round 3: the Pain beat (project_brief.md
Section 1.6, 10-25s) narrates sourced statistics (FBI IC3 2024 / D-14,
RFC 7489 / D-13, NDSS 2015 / D-07) with three small on-screen source
chips — these never existed in the codebase before this fix.
"""

from jinja2 import Environment, FileSystemLoader

_env = Environment(loader=FileSystemLoader("templates"))


def _render(**context):
    defaults = {"brand": "example.com", "generated": 150, "replay": False}
    defaults.update(context)
    return _env.get_template("_progress.html").render(**defaults)


def test_progress_page_shows_the_three_scripted_source_chips():
    html = _render()
    assert "FBI IC3 2024" in html
    assert "RFC 7489" in html
    assert "NDSS 2015" in html


def test_source_chips_link_to_the_dossier_sources():
    html = _render()
    assert "ic3.gov/AnnualReport/Reports/2024_IC3Report.pdf" in html
    assert "rfc-editor.org/rfc/rfc7489.html" in html
    assert "ndss-symposium.org/ndss2015" in html
