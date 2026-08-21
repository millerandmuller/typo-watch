from squatwatch.models import Card, ProbeInfo, ProbeKind, RdapInfo
from squatwatch.notice import draft_notice


def _card(**overrides):
    defaults = dict(
        domain="drvnetwork.com",
        cls="replacement",
        rdap=RdapInfo(registrar="Example Registrar", abuse_email="abuse@example-registrar.com"),
        probe=ProbeInfo(kind=ProbeKind.MAIL_ONLY, mx=["mail.drvnetwork.com"]),
    )
    defaults.update(overrides)
    return Card(**defaults)


def test_notice_includes_the_mx_line_when_mail_is_genuinely_configured():
    draft = draft_notice(_card(), "devnetwork.com")
    assert "Mail exchange configured: mail.drvnetwork.com" in draft


def test_notice_omits_the_mx_line_when_probe_mx_is_empty():
    """B2 (project_brief.md Section 9b): once probe.classify() filters
    placeholder MX hosts (localhost, null MX, parking-provider zones) out
    of card.probe.mx, the notice draft must not claim mail is configured
    for a domain that has none — the tmx.org acceptance case."""
    card = _card(
        domain="tmx.org",
        probe=ProbeInfo(kind=ProbeKind.PARKED, mx=[]),
    )
    draft = draft_notice(card, "devnetwork.com")
    assert "Mail exchange configured" not in draft
    assert "mail exchange" not in draft.lower()
