"""F6 — danger ranking (rules half). Pure functions, no I/O, no model call.

Rule weights and banding exactly as documented on the methodology page
(project_brief.md Section 6, "Rule weights"): keyword class +3, MX
present +3, appears in Google +2, homoglyph or omission +2, created
within 12 months +1, parked -1; forwards-home sets band `yours`
regardless of score; a purchasable/free candidate sets band `free` with
score from class priors only (keyword + confusable — the signals that
still mean something before a domain is ever registered).

Ordering is reproducible from the rules alone (F6 acceptance) — the
model in squatwatch.reason writes prose, never band or score.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from squatwatch.models import Band, Card, ProbeKind, ScoreBreakdown

_CONFUSABLE_CLASSES = {"homoglyph", "omission"}
_KEYWORD_CLASSES = {"combosquat"}
_RECENT_WINDOW = timedelta(days=365)

# "Established, likely unrelated" — a stranger-held domain whose
# registration is old enough (more than 10 years at scan time) and
# specific enough (a live site with its own title, not just parked) that
# it almost certainly is a dictionary-word or acronym collision, not a
# squatter. 10 years is judgment, documented on the methodology page, not
# a sourced fact. Only live-other qualifies — mail-only, parked, dark and
# unknown never get the -3 or the sort push, since none of those show
# independent, ongoing use of the name.
ESTABLISHED_YEARS_THRESHOLD = 10
_ESTABLISHED_PENALTY = -3


def parse_rdap_created(created: Optional[str]) -> Optional[datetime]:
    if not created:
        return None
    try:
        return datetime.fromisoformat(created.replace("Z", "+00:00"))
    except ValueError:
        return None


def _created_within_window(created: Optional[str]) -> bool:
    dt = parse_rdap_created(created)
    if dt is None:
        return False
    return datetime.now(timezone.utc) - dt <= _RECENT_WINDOW


def is_established_unrelated(card: Card) -> bool:
    """Principle 4, rules only — see module docstring above."""
    if card.probe.kind != ProbeKind.LIVE_OTHER or not card.probe.title:
        return False
    dt = parse_rdap_created(card.rdap.created)
    if dt is None:
        return False
    age = datetime.now(timezone.utc) - dt
    return age > timedelta(days=365 * ESTABLISHED_YEARS_THRESHOLD)


def _full_score(card: Card) -> ScoreBreakdown:
    keyword = 3 if card.cls in _KEYWORD_CLASSES else 0
    mx = 3 if card.probe.mx else 0
    search = 2 if card.search.appears else 0
    confusable = 2 if card.cls in _CONFUSABLE_CLASSES else 0
    recent = 1 if _created_within_window(card.rdap.created) else 0
    parked = -1 if card.probe.kind == ProbeKind.PARKED else 0
    established = _ESTABLISHED_PENALTY if is_established_unrelated(card) else 0
    total = keyword + mx + search + confusable + recent + parked + established
    return ScoreBreakdown(
        keyword=keyword, mx=mx, search=search, confusable=confusable,
        recent=recent, parked=parked, established=established, total=total,
    )


def _prior_only_score(card: Card) -> ScoreBreakdown:
    keyword = 3 if card.cls in _KEYWORD_CLASSES else 0
    confusable = 2 if card.cls in _CONFUSABLE_CLASSES else 0
    return ScoreBreakdown(keyword=keyword, confusable=confusable, total=keyword + confusable)


def score_and_band(card: Card) -> Card:
    """Mutate and return `card` with .band and .score set from rules."""
    if card.probe.kind == ProbeKind.FORWARDS_HOME:
        card.band = Band.YOURS
        card.score = _full_score(card)
        return card

    if card.registered is False:
        card.band = Band.FREE
        card.score = _prior_only_score(card)
        return card

    if card.registered is True:
        card.band = Band.STRANGERS
        card.score = _full_score(card)
        return card

    # registered is None: registry answer pending — no band yet.
    card.band = None
    card.score = ScoreBreakdown()
    return card


def sort_within_bands(cards: list[Card]) -> list[Card]:
    """Section 4 step 7: cards sorted by score within their band.

    "Established, likely unrelated" cards sort after every other card in
    the strangers band, unconditionally — not just usually, via a low
    enough score. A genuine squatter could coincidentally score just as
    low, so the -3 penalty alone wouldn't guarantee last place; the
    explicit tier below does.
    """
    return sorted(
        cards,
        key=lambda c: (
            0 if c.band is None else 1,
            c.band.value if c.band else "",
            is_established_unrelated(c),
            -c.score.total,
            c.domain,
        ),
    )
