"""F1 — permutation engine.

Pure functions, no I/O. Classes mirror dnstwist's list (D-09) plus
combosquat keywords (D-08) and TLD swaps (project_brief.md Section 3, F1
and Section 4 step 2). Deterministic for a given input domain: same
input always yields the same candidate list in the same order.
"""

from __future__ import annotations

import string
from dataclasses import dataclass

import tldextract

_EXTRACT = tldextract.TLDExtract(suffix_list_urls=())

# QWERTY physical-adjacency map used for replacement/insertion typos.
_KEYBOARD_ADJACENT: dict[str, str] = {
    "q": "wa", "w": "qeas", "e": "wrds", "r": "etdf", "t": "ryfg",
    "y": "tugh", "u": "yihj", "i": "uojk", "o": "ipkl", "p": "ol",
    "a": "qwsz", "s": "awedxz", "d": "serfxc", "f": "drtgcv", "g": "ftyhvb",
    "h": "gyujbn", "j": "huikmn", "k": "jiolm", "l": "kop",
    "z": "asx", "x": "zsdc", "c": "xdfv", "v": "cfgb", "b": "vghn",
    "n": "bhjm", "m": "njk",
    "1": "2q", "2": "13qw", "3": "24we", "4": "35er", "5": "46rt",
    "6": "57ty", "7": "68yu", "8": "79ui", "9": "80io", "0": "9p",
}

# Bidirectional substring substitutions (project_brief.md Section 3, F1):
# rn/m, vv/w, l/1/I, 0/o, cl/d.
_HOMOGLYPH_PAIRS: tuple[tuple[str, str], ...] = (
    ("rn", "m"),
    ("vv", "w"),
    ("l", "1"),
    ("l", "I"),
    ("1", "I"),
    ("0", "o"),
    ("cl", "d"),
)

_VOWELS = "aeiou"

_COMBOSQUAT_KEYWORDS = (
    "login", "secure", "pay", "support", "account",
    "mail", "verify", "billing", "help",
)

# Identity Digital TLDs plus the common generic swaps named in the brief
# (Section 4, step 2).
_TLD_SWAPS = ("co", "net", "org", "io", "app", "agency", "solutions", "watch")

# Risk priors per class — used only to rank/truncate to ~150 candidates,
# never to decide band or score (that stays the rank module's job).
CLASS_PRIOR: dict[str, float] = {
    "homoglyph": 0.90,
    "combosquat": 0.85,
    "omission": 0.80,
    "transposition": 0.80,
    "replacement": 0.70,
    "tld-swap": 0.65,
    "insertion": 0.60,
    "vowel-swap": 0.50,
    "repetition": 0.50,
    "hyphenation": 0.40,
    "bitsquatting": 0.30,
}

DEFAULT_MAX_CANDIDATES = 150


@dataclass(frozen=True)
class Candidate:
    domain: str
    cls: str
    prior: float


@dataclass(frozen=True)
class ParsedBrand:
    label: str
    tld: str
    registrable: str


def parse_brand(raw: str) -> ParsedBrand:
    """Normalise raw input to a registrable domain (public-suffix aware).

    Strips scheme/path/whitespace, lowercases, and rejects input that
    does not resolve to a domain + suffix (edge case #8 in the brief),
    or that violates RFC 1035 length limits (63 chars/label, 253 total)
    — examiner_report.md Round 1 P2: an unvalidated 300-char label
    reached name.com's checkAvailability, whose batch call then failed
    outright with no visible degrade notice, leaving a coverage footer
    that didn't add up. Reject it here instead, before it costs an API
    call.
    """
    candidate = raw.strip().lower()
    for prefix in ("https://", "http://"):
        if candidate.startswith(prefix):
            candidate = candidate[len(prefix):]
    candidate = candidate.split("/", 1)[0]
    candidate = candidate.split("?", 1)[0]
    candidate = candidate.split(":", 1)[0]

    if len(candidate) > 253:
        raise ValueError(f"domain too long: {raw!r}")
    if any(len(label) > 63 for label in candidate.split(".")):
        raise ValueError(f"domain label too long: {raw!r}")

    result = _EXTRACT(candidate)
    if not result.domain or not result.suffix:
        raise ValueError(f"not a registrable domain: {raw!r}")
    return ParsedBrand(
        label=result.domain,
        tld=result.suffix,
        registrable=f"{result.domain}.{result.suffix}",
    )


def _omissions(label: str) -> list[str]:
    return [label[:i] + label[i + 1:] for i in range(len(label)) if len(label) > 1]


def _transpositions(label: str) -> list[str]:
    out = []
    for i in range(len(label) - 1):
        out.append(label[:i] + label[i + 1] + label[i] + label[i + 2:])
    return out


def _replacements(label: str) -> list[str]:
    out = []
    for i, ch in enumerate(label):
        for adj in _KEYBOARD_ADJACENT.get(ch, ""):
            out.append(label[:i] + adj + label[i + 1:])
    return out


def _insertions(label: str) -> list[str]:
    out = []
    for i, ch in enumerate(label):
        for adj in _KEYBOARD_ADJACENT.get(ch, ""):
            out.append(label[:i] + adj + label[i:])
            out.append(label[:i + 1] + adj + label[i + 1:])
    return out


def _repetitions(label: str) -> list[str]:
    return [label[:i] + ch + label[i:] for i, ch in enumerate(label)]


def _homoglyphs(label: str) -> list[str]:
    out = []
    for src, dst in _HOMOGLYPH_PAIRS:
        start = 0
        while True:
            idx = label.find(src, start)
            if idx == -1:
                break
            out.append(label[:idx] + dst + label[idx + len(src):])
            start = idx + 1
        start = 0
        while True:
            idx = label.find(dst, start)
            if idx == -1:
                break
            out.append(label[:idx] + src + label[idx + len(dst):])
            start = idx + 1
    return out


def _hyphenations(label: str) -> list[str]:
    return [label[:i] + "-" + label[i:] for i in range(1, len(label))]


def _vowel_swaps(label: str) -> list[str]:
    out = []
    for i, ch in enumerate(label):
        if ch in _VOWELS:
            for v in _VOWELS:
                if v != ch:
                    out.append(label[:i] + v + label[i + 1:])
    return out


def _bitsquats(label: str) -> list[str]:
    allowed = set(string.ascii_lowercase + string.digits + "-")
    out = []
    for i, ch in enumerate(label):
        byte = ord(ch)
        for bit in range(8):
            flipped = chr(byte ^ (1 << bit))
            if flipped in allowed and flipped != ch:
                out.append(label[:i] + flipped + label[i + 1:])
    return out


def _combosquats(label: str) -> list[str]:
    out = []
    for kw in _COMBOSQUAT_KEYWORDS:
        out.append(f"{label}-{kw}")
        out.append(f"{kw}-{label}")
        out.append(f"{label}{kw}")
        out.append(f"{kw}{label}")
    return out


_LABEL_GENERATORS: tuple[tuple[str, "callable[[str], list[str]]"], ...] = (
    ("omission", _omissions),
    ("transposition", _transpositions),
    ("replacement", _replacements),
    ("insertion", _insertions),
    ("repetition", _repetitions),
    ("homoglyph", _homoglyphs),
    ("hyphenation", _hyphenations),
    ("vowel-swap", _vowel_swaps),
    ("bitsquatting", _bitsquats),
    ("combosquat", _combosquats),
)


def _valid_label(label: str) -> bool:
    if not label or len(label) > 63:
        return False
    if label.startswith("-") or label.endswith("-"):
        return False
    return all(c in string.ascii_lowercase + string.digits + "-" for c in label)


def generate(
    brand: str, max_candidates: int = DEFAULT_MAX_CANDIDATES
) -> tuple[list[Candidate], int]:
    """Generate permutation candidates for a brand's registrable domain.

    Returns (candidates, total_before_truncation) — the count is needed
    for the coverage footer's "150 of 412 candidates checked" wording
    (edge case #9). Deterministic: iterates classes and matches in a
    fixed order, dedupes by domain, sorts by (prior desc, domain asc).
    """
    parsed = parse_brand(brand)
    seen: dict[str, Candidate] = {}

    for cls, generator_fn in _LABEL_GENERATORS:
        prior = CLASS_PRIOR[cls]
        for new_label in generator_fn(parsed.label):
            if new_label == parsed.label or not _valid_label(new_label):
                continue
            domain = f"{new_label}.{parsed.tld}"
            if domain not in seen:
                seen[domain] = Candidate(domain=domain, cls=cls, prior=prior)

    prior = CLASS_PRIOR["tld-swap"]
    for new_tld in _TLD_SWAPS:
        if new_tld == parsed.tld:
            continue
        domain = f"{parsed.label}.{new_tld}"
        if domain not in seen:
            seen[domain] = Candidate(domain=domain, cls="tld-swap", prior=prior)

    ordered = sorted(seen.values(), key=lambda c: (-c.prior, c.domain))
    total = len(ordered)
    return ordered[:max_candidates], total
