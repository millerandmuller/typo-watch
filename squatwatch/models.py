"""Data shapes shared across the scan pipeline.

Field names and nesting follow project_brief.md Section 6 "Data shapes"
exactly, so a Card serialised here is the same JSON the brief documents
and the same JSON the raw-response popover on the result page renders.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

PERMUTATION_CLASSES = (
    "omission",
    "transposition",
    "replacement",
    "insertion",
    "repetition",
    "homoglyph",
    "hyphenation",
    "vowel-swap",
    "bitsquatting",
    "combosquat",
    "tld-swap",
)


class Band(str, Enum):
    STRANGERS = "strangers"
    YOURS = "yours"
    FREE = "free"


class ProbeKind(str, Enum):
    FORWARDS_HOME = "forwards-home"
    LIVE_OTHER = "live-other"
    PARKED = "parked"
    MAIL_ONLY = "mail-only"
    DARK = "dark"
    UNKNOWN = "unknown"


class Availability(BaseModel):
    purchasable: Optional[bool] = None
    price: Optional[float] = None
    premium: Optional[bool] = None


class RdapInfo(BaseModel):
    registrar: Optional[str] = None
    nameservers: list[str] = Field(default_factory=list)
    created: Optional[str] = None
    abuse_email: Optional[str] = None
    source: Optional[str] = None


class ProbeInfo(BaseModel):
    a: list[str] = Field(default_factory=list)
    mx: list[str] = Field(default_factory=list)
    chain: list[str] = Field(default_factory=list)
    final_host: Optional[str] = None
    kind: Optional[ProbeKind] = None
    title: Optional[str] = None


class SearchInfo(BaseModel):
    checked: bool = False
    appears: Optional[bool] = None
    first_title: Optional[str] = None
    # Only meaningful when checked=False: "quota" (per-scan cap hit),
    # "error" (API/timeout/transport failure), "no_key" (SERPAPI_API_KEY
    # unset). None when checked=True. Drives the distinct copy in
    # templates/_macros.html (A1, project_brief.md Section 9b).
    reason: Optional[str] = None


class ScoreBreakdown(BaseModel):
    keyword: int = 0
    mx: int = 0
    search: int = 0
    confusable: int = 0
    recent: int = 0
    parked: int = 0
    total: int = 0


class Card(BaseModel):
    domain: str
    cls: str
    prior: float = 0.0
    registered: Optional[bool] = None
    authoritative: bool = True
    availability: Availability = Field(default_factory=Availability)
    rdap: RdapInfo = Field(default_factory=RdapInfo)
    probe: ProbeInfo = Field(default_factory=ProbeInfo)
    search: SearchInfo = Field(default_factory=SearchInfo)
    score: ScoreBreakdown = Field(default_factory=ScoreBreakdown)
    band: Optional[Band] = None
    land_line: Optional[str] = None
    reason: Optional[str] = None


class CoverageFooter(BaseModel):
    generated: int = 0
    answered: int = 0
    not_authoritative: int = 0
    truncated_from: Optional[int] = None


class PricesInfo(BaseModel):
    top5_sum: Optional[float] = None
    top5_domains: list[str] = Field(default_factory=list)
    top5_priced_count: int = 0
    top5_total_count: int = 0


class SuggestedName(BaseModel):
    domain_name: str
    purchasable: Optional[bool] = None
    price: Optional[float] = None


class ScanResult(BaseModel):
    brand: str
    scanned_at: str
    cards: list[Card] = Field(default_factory=list)
    footer: CoverageFooter = Field(default_factory=CoverageFooter)
    prices: PricesInfo = Field(default_factory=PricesInfo)
    replay: bool = False
    replay_label: Optional[str] = None
    slowed_down: bool = False
    suggestions: list[SuggestedName] = Field(default_factory=list)

    def band_counts(self) -> dict[str, int]:
        counts = {Band.STRANGERS.value: 0, Band.YOURS.value: 0, Band.FREE.value: 0}
        for card in self.cards:
            if card.band is not None:
                counts[card.band.value] += 1
        return counts
