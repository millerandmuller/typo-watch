"""B (land line) and fixed UI strings.

🔄 KONSULTATION: [🎓 Domain — D-05, D-06, D-10, D-13] — every line here
names a consequence the small-shop admin persona (project_brief.md
Section H.E) would recognise without a glossary. Plain, specific,
unalarmed; second person; no exclamation marks; no "threat actor" /
"attack surface" (Section 5, Voice and tone). Wording is fixed and
changes only via the Praktiker, per Section 5.
"""

from __future__ import annotations

from datetime import datetime

from squatwatch.models import Card, ProbeKind
from squatwatch.rank import parse_rdap_created, is_established_unrelated

# Section 5, "UI strings (fixed; changes only via the Praktiker, meaning
# never changes)" — verbatim.
INPUT_PLACEHOLDER = "your-brand.com"
MAIL_ONLY_LINE = "Can receive your customers' email. No website."
NOT_COVERED_LINE = (
    "Not covered: look-alikes on someone else's subdomain (brand.example.net), "
    "free-hosting pages, non-Latin homographs beyond our table, social handles. "
    "A determined attacker uses these too."
)


def forwards_home_line(brand: str) -> str:
    return f"Already yours. Ends on www.{brand} after one redirect."


def sandbox_label(price_per_year: float | None = None) -> str:
    """`price_per_year` must be the price shared by every domain in this
    batch. A batch spanning more than one price (mixed TLDs/candidates)
    has no single figure to state honestly here — pass None and each
    item's own price still shows on its own line (_defend_result.html).
    """
    if price_per_year is None:
        return "Sandbox registration (name.com test environment)."
    return f"Sandbox registration (name.com test environment). Production price: ${price_per_year:.2f}/yr."


def _parse_scanned_at(scanned_at: str) -> datetime:
    """Shared ISO-8601 parser for `scanned_at` timestamps (stored with
    microseconds, for SQLite primary-key precision). Every human-facing
    label built from `scanned_at` goes through this, never a raw
    interpolation (examiner_report.md Round 1 P2: two examiners
    independently caught the raw ISO string leaking into a label).
    """
    return datetime.strptime(scanned_at.split(".")[0].rstrip("Z"), "%Y-%m-%dT%H:%M:%S")


def replay_label(replayed_from_utc: str) -> str:
    """Section 5's fixed, verbatim format is "YYYY-MM-DD HH:MM UTC"."""
    try:
        formatted = _parse_scanned_at(replayed_from_utc).strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        formatted = replayed_from_utc
    return f"Replayed from {formatted}. Live mode: remove ?replay=1."


def scanned_label(scanned_at: str) -> str:
    """A7 (project_brief.md Section 9c): a live (non-replay) result shows
    its own human-formatted timestamp above the first band, in the same
    fixed format as `replay_label` — a permalink or fresh scan must
    never leak the raw ISO-8601 `scanned_at` string either."""
    try:
        formatted = _parse_scanned_at(scanned_at).strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        formatted = scanned_at
    return f"Scanned {formatted}."


def _plural(n: int, singular: str, plural: str) -> str:
    return singular if n == 1 else plural


def watch_diff_line(diff: dict) -> str:
    """A7: the watch-mode diff footer as one grammatical sentence.
    `diff["since"]` is reformatted to a human date ("14 Aug 2026"), and
    each clause takes the plural form its count actually needs: a noun
    plural for counted things ("registration"/"registrations"), and a
    verb-agreement form for the forwards-to-you clause ("forwards" only
    agrees with exactly 1; 0 or many take "forward", e.g. "0 now forward
    to you"). "newly free" is an adjective phrase and never pluralizes.

    Falls back to the raw `since` string on a malformed timestamp,
    matching `scanned_label`/`replay_label`'s own degrade-gracefully
    behavior (Round 4 adversarial re-review: this call was previously
    unguarded and would crash the page with an unhandled 500).
    """
    try:
        dt = _parse_scanned_at(diff["since"])
        since = f"{dt.day} {dt.strftime('%b %Y')}"
    except ValueError:
        since = diff["since"]
    reg_n = len(diff["new_registrations"])
    fwd_n = len(diff["now_forwards_to_you"])
    free_n = len(diff["newly_free"])
    reg_word = _plural(reg_n, "registration", "registrations")
    fwd_verb = _plural(fwd_n, "forwards", "forward")
    return (
        f"Since {since}: {reg_n} new {reg_word}, "
        f"{fwd_n} now {fwd_verb} to you, {free_n} newly free."
    )


def coverage_footer_line(generated: int, answered: int, not_authoritative: int) -> str:
    return (
        f"{generated} generated · {answered} answered by the registry · "
        f"{not_authoritative} not authoritative (no RDAP server for this TLD)"
    )


def land_line(card: Card) -> str:
    """B — one line per stranger-held card (Section 3, F: 'Where your
    customers land'). Every stranger-held card gets exactly one of these.
    """
    if is_established_unrelated(card):
        dt = parse_rdap_created(card.rdap.created)
        return f"Established site since {dt.year}, probably unrelated to you."

    kind = card.probe.kind
    if kind == ProbeKind.PARKED:
        return "Parked for sale."
    if kind == ProbeKind.LIVE_OTHER:
        if card.probe.title:
            return f"Live site titled ‘{card.probe.title}’."
        return "Live site, no title captured."
    if kind == ProbeKind.MAIL_ONLY:
        return MAIL_ONLY_LINE
    if kind == ProbeKind.DARK:
        return "Nothing answers."
    # ProbeKind.UNKNOWN or unset: the registry confirmed this domain is
    # registered (that's why it's in the strangers band at all) — it's
    # the DNS/HTTP probe that couldn't determine where it points.
    return "Could not determine where this points."
