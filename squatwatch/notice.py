"""F9 — notice draft.

Deterministic template filled from RDAP + probe facts already on the
card; cites the three UDRP elements (D-19, D-20). Never contains a fact
absent from the card (F9 acceptance) — a missing field is a missing
line, never a guess. The abuse address is the RDAP one or "not
published" (D-21: registrars are obliged to publish one, but our own
lookup may not have found it). "Draft, not sent" is not a UI label
tacked on afterward — it is baked into the text itself, since this
function's output can be copied verbatim.

An optional tone-only polish (never a fact-changing one) lives in
squatwatch.reason.polish_notice — the template below is already
complete and correct without it.
"""

from __future__ import annotations

from squatwatch.models import Card

_VOWEL_LEADING = ("a", "e", "i", "o", "u")


def _article(word: str) -> str:
    return "an" if word[:1].lower() in _VOWEL_LEADING else "a"


def draft_notice(card: Card, brand: str) -> str:
    abuse_email = card.rdap.abuse_email or "not published"
    registrar = card.rdap.registrar or "the registrar on file"
    lines = [
        f"Subject: Look-alike domain of {brand} — {card.domain}",
        "",
        f"To: {abuse_email}",
        "",
        f"This is a draft notice about {card.domain}, a domain that closely resembles "
        f"{brand}. It has not been sent.",
        "",
        "Under the Uniform Domain-Name Dispute-Resolution Policy (UDRP), which every "
        "ICANN-accredited registrar is bound by, a complaint rests on three elements:",
        f"  1. Confusing similarity — {card.domain} is {_article(card.cls)} {card.cls} "
        f"variant of {brand}.",
        "  2. No legitimate interest — no connection to this business is evident from "
        "the facts below.",
        "  3. Bad faith — assessed from the facts below; we make no claim about intent "
        "beyond what is shown.",
        "",
        "Facts on file for this domain:",
        f"  - Registrar: {registrar}",
    ]
    if card.rdap.created:
        lines.append(f"  - Created: {card.rdap.created}")
    if card.rdap.nameservers:
        lines.append(f"  - Nameservers: {', '.join(card.rdap.nameservers)}")
    if card.probe.mx:
        lines.append(f"  - Mail exchange configured: {', '.join(card.probe.mx)}")
    if card.probe.kind:
        lines.append(f"  - Observed use: {card.probe.kind.value}")
    if card.search.checked and card.search.appears:
        lines.append(f"  - Appears in Google search: \"{card.search.first_title}\"")
    lines += [
        "",
        "We ask that this be reviewed against the registrar's abuse policy. A formal "
        "UDRP complaint (WIPO fee USD 1,500 for one to five domains) remains available "
        "if this is not resolved directly.",
        "",
        "This is a draft. It has not been sent.",
    ]
    return "\n".join(lines)
