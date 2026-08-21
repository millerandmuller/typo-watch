"""T-01 (project_brief.md dossier): permutation engine correctness."""

from squatwatch.engine import CLASS_PRIOR, generate, parse_brand


def test_parse_brand_normalises_scheme_and_path():
    assert parse_brand("https://www.name.com/path?x=1").registrable in (
        "www.name.com",
        "name.com",
    )
    # bare label.tld with no www subdomain
    assert parse_brand("name.com").registrable == "name.com"


def test_parse_brand_rejects_non_domain():
    import pytest

    for bad in ("name", "http://localhost", "192.168.0.1"):
        with pytest.raises(ValueError):
            parse_brand(bad)


def test_narne_generated_as_homoglyph():
    """T-01: narne.com must appear, tagged homoglyph (m -> rn)."""
    candidates, _total = generate("name.com", max_candidates=1000)
    by_domain = {c.domain: c for c in candidates}
    assert "narne.com" in by_domain
    assert by_domain["narne.com"].cls == "homoglyph"


def test_at_least_one_candidate_per_class():
    candidates, _total = generate("name.com", max_candidates=1000)
    classes_seen = {c.cls for c in candidates}
    expected = set(CLASS_PRIOR.keys())
    missing = expected - classes_seen
    assert not missing, f"no candidate generated for classes: {missing}"


def test_deterministic_output():
    a, total_a = generate("name.com")
    b, total_b = generate("name.com")
    assert [c.domain for c in a] == [c.domain for c in b]
    assert [c.cls for c in a] == [c.cls for c in b]
    assert total_a == total_b


def test_cap_and_truncation_count():
    candidates, total = generate("name.com", max_candidates=50)
    assert len(candidates) == 50
    assert total >= 50


def test_no_duplicates_and_excludes_original():
    candidates, _total = generate("name.com", max_candidates=1000)
    domains = [c.domain for c in candidates]
    assert len(domains) == len(set(domains))
    assert "name.com" not in domains


def test_short_brand_devnetwork():
    candidates, total = generate("devnetwork.com")
    assert total > 0
    assert len(candidates) <= 150


def test_cctld_brand_shop_de():
    parsed = parse_brand("shop.de")
    assert parsed.tld == "de"
    candidates, _total = generate("shop.de", max_candidates=1000)
    assert all(c.domain.endswith(".de") or not c.domain.endswith(".de") for c in candidates)
    # at least the tld-swap class should still fire even for a ccTLD brand
    assert any(c.cls == "tld-swap" for c in candidates)


def test_parse_brand_rejects_rfc1035_length_violations():
    """examiner_report.md Round 1, P2: a 300-char label reached
    name.com's checkAvailability and broke the coverage footer's
    arithmetic with no visible degrade — reject it before it costs an
    API call."""
    import pytest

    with pytest.raises(ValueError):
        parse_brand("a" * 64 + ".com")  # label over 63 chars
    with pytest.raises(ValueError):
        parse_brand("a" * 300 + ".com")  # total over 253 chars
    # a normal, valid long-ish label must still work
    assert parse_brand("a" * 60 + ".com").registrable == ("a" * 60 + ".com")
