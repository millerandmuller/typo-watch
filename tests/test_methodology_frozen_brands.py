"""B1 (project_brief.md Section 9c): the methodology page states, in one
sentence, that a curated demo brand's watch history is the committed
seed pair and live scans are not added to it -- so a viewer isn't misled
into thinking the "Since 14 Aug 2026: ..." diff reflects ordinary live
watch behaviour. Rendered directly through Jinja2, same templates/
directory squatwatch.app points at.
"""

from jinja2 import Environment, FileSystemLoader

_env = Environment(loader=FileSystemLoader("templates"))


def _render(snapshot_frozen_brands):
    return _env.get_template("methodology.html").render(
        serpapi_max_queries=10,
        namecom_budget_used=0,
        serpapi_account=None,
        snapshot_frozen_brands=snapshot_frozen_brands,
    )


def test_methodology_states_the_frozen_brand_sentence_when_one_is_configured():
    html = _render(["devnetwork.com"])
    assert (
        "For the curated demo brand (devnetwork.com) the watch history shown "
        "is the committed seed pair; live scans are not added to it." in html
    )


def test_methodology_omits_the_sentence_when_no_brand_is_frozen():
    html = _render([])
    assert "committed seed pair" not in html


def test_methodology_pluralizes_for_more_than_one_frozen_brand():
    html = _render(["devnetwork.com", "example.com"])
    assert "curated demo brands (devnetwork.com, example.com)" in html
