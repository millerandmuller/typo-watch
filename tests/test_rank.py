import inspect
from datetime import datetime, timedelta, timezone
from pathlib import Path

from squatwatch.copy import land_line
from squatwatch.models import Availability, Band, Card, ProbeInfo, ProbeKind, RdapInfo, SearchInfo
from squatwatch import rank
from squatwatch.rank import score_and_band, sort_within_bands


def _card(**overrides) -> Card:
    base = dict(domain="narne.com", cls="homoglyph")
    base.update(overrides)
    return Card(**base)


def test_forwards_home_sets_yours_regardless_of_score():
    card = _card(registered=True, probe=ProbeInfo(kind=ProbeKind.FORWARDS_HOME))
    result = score_and_band(card)
    assert result.band == Band.YOURS


def test_purchasable_sets_free_with_prior_only_score():
    card = _card(cls="combosquat", registered=False, availability=Availability(purchasable=True))
    result = score_and_band(card)
    assert result.band == Band.FREE
    assert result.score.keyword == 3
    assert result.score.mx == 0  # not scored for free band
    assert result.score.total == 3


def test_registered_stranger_full_score():
    card = _card(
        cls="homoglyph",
        registered=True,
        probe=ProbeInfo(kind=ProbeKind.MAIL_ONLY, mx=["mail.narne.com"]),
        search=SearchInfo(checked=True, appears=True),
    )
    result = score_and_band(card)
    assert result.band == Band.STRANGERS
    assert result.score.mx == 3
    assert result.score.search == 2
    assert result.score.confusable == 2
    assert result.score.total == 7  # matches the worked example in the brief


def test_parked_subtracts_one():
    card = _card(cls="omission", registered=True, probe=ProbeInfo(kind=ProbeKind.PARKED))
    result = score_and_band(card)
    assert result.score.parked == -1


def test_recent_creation_adds_one():
    recent = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    card = _card(cls="insertion", registered=True, probe=ProbeInfo(kind=ProbeKind.DARK))
    card.rdap.created = recent
    result = score_and_band(card)
    assert result.score.recent == 1


def test_pending_registration_has_no_band():
    card = _card(registered=None)
    result = score_and_band(card)
    assert result.band is None


def test_sort_within_bands_orders_by_score_desc_within_band():
    a = score_and_band(_card(domain="a.com", registered=True, probe=ProbeInfo(kind=ProbeKind.DARK)))
    b = score_and_band(
        _card(
            domain="b.com",
            cls="combosquat",
            registered=True,
            probe=ProbeInfo(kind=ProbeKind.MAIL_ONLY, mx=["mx.b.com"]),
        )
    )
    ordered = sort_within_bands([a, b])
    assert ordered[0].domain == "b.com"  # higher score first
    assert ordered[1].domain == "a.com"


def test_established_unrelated_downgrades_sorts_last_and_relabels():
    """/academy-fix: an old, titled, live stranger-held site (nme.com-
    style — a real dictionary-word collision, not a squatter) gets -3,
    sorts after every other strangers-band card, and its own land line —
    even though its raw score alone wouldn't guarantee last place. A
    mail-only card created this year (drvnetwork.com-style) is untouched
    by the rule: wrong probe kind AND well within the 10-year window."""
    old_created = (datetime.now(timezone.utc) - timedelta(days=365 * 28)).isoformat()
    established = score_and_band(
        _card(
            domain="nme.com",
            cls="replacement",  # not a keyword/confusable class — isolates the -3
            registered=True,
            probe=ProbeInfo(kind=ProbeKind.LIVE_OTHER, title="NME | Music News, Reviews"),
            rdap=RdapInfo(created=old_created),
        )
    )
    assert established.score.total == -3
    # exact year depends on "today," so assert the created year is embedded
    # rather than hardcoding a specific year
    created_year = datetime.fromisoformat(old_created).year
    assert land_line(established) == f"Established site since {created_year}, probably unrelated to you."

    recent_created = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    untouched = score_and_band(
        _card(
            domain="drvnetwork.com",
            cls="replacement",
            registered=True,
            probe=ProbeInfo(kind=ProbeKind.MAIL_ONLY, mx=["mail.drvnetwork.com"]),
            rdap=RdapInfo(created=recent_created),
        )
    )
    assert untouched.score.total == 4  # +3 mx, +1 recent — no established penalty
    assert land_line(untouched) == "Can receive your customers' email. No website."

    # A worse-scoring genuine squatter must still sort BEFORE the
    # established/unrelated card — the tier, not just the score, decides.
    squatter = score_and_band(
        _card(domain="darkone.com", cls="replacement", registered=True, probe=ProbeInfo(kind=ProbeKind.DARK))
    )
    assert squatter.score.total == 0 > established.score.total
    ordered = sort_within_bands([established, squatter])
    assert [c.domain for c in ordered] == ["darkone.com", "nme.com"]


def test_score_breakdown_components_sum_to_total_on_a_demoted_card():
    """A2 (project_brief.md Section 9e): the -3 established penalty used
    to be folded into `total` with no component field, so the evidence
    panel's rendered lines (keyword/mx/search/confusable/recent/parked)
    summed to a number that didn't match the displayed total. Every
    component, including `established`, must now sum to `total`."""
    old_created = (datetime.now(timezone.utc) - timedelta(days=365 * 28)).isoformat()
    demoted = score_and_band(
        _card(
            domain="nme.com",
            cls="replacement",
            registered=True,
            probe=ProbeInfo(kind=ProbeKind.LIVE_OTHER, title="NME | Music News, Reviews"),
            rdap=RdapInfo(created=old_created),
        )
    )
    b = demoted.score
    assert b.total == -3
    assert b.keyword + b.mx + b.search + b.confusable + b.recent + b.parked + b.established == b.total
    assert b.established == -3


def test_score_breakdown_established_is_zero_and_unrendered_line_when_not_demoted():
    """A non-demoted card's `established` component is 0 -- the template
    guard (`_macros.html`) only renders the "established, likely
    unrelated" line when this field is non-zero."""
    recent_created = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    untouched = score_and_band(
        _card(
            domain="drvnetwork.com",
            cls="replacement",
            registered=True,
            probe=ProbeInfo(kind=ProbeKind.MAIL_ONLY, mx=["mail.drvnetwork.com"]),
            rdap=RdapInfo(created=recent_created),
        )
    )
    b = untouched.score
    assert b.established == 0
    assert b.keyword + b.mx + b.search + b.confusable + b.recent + b.parked + b.established == b.total


def test_established_unrelated_wording_matches_rank_py_not_brand_relative():
    """Section 9c A5: rank.py's rule is registration age at scan time
    (datetime.now() - rdap.created), never brand-relative — so neither
    the module docstring nor the methodology page may describe it as
    the registration "predating the brand"."""
    source = inspect.getsource(rank)
    assert "predates the brand" not in source

    page = Path("templates/methodology.html").read_text()
    assert "predates the brand" not in page
    assert "more than 10 years old at scan time" in page
