import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from squatwatch.config import AnthropicConfig
from squatwatch.models import Band, Card, ProbeInfo, ProbeKind, ScoreBreakdown, SearchInfo
from squatwatch.reason import (
    MAX_MODEL_BATCH,
    MODEL_BATCH_CHUNK_SIZE,
    _deterministic_reason,
    _fact_tuple,
    _mentions_search,
    write_reasons,
)


def _card(domain, score_total, band=Band.STRANGERS, search=None):
    return Card(
        domain=domain,
        cls="homoglyph",
        band=band,
        probe=ProbeInfo(kind=ProbeKind.MAIL_ONLY, mx=["mx.example.com"]),
        score=ScoreBreakdown(total=score_total),
        search=search or SearchInfo(),
    )


def _mock_response(reasons_by_domain):
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = json.dumps(
        {"reasons": [{"domain": d, "reason": r} for d, r in reasons_by_domain.items()]}
    )
    resp = MagicMock()
    resp.content = [text_block]
    return resp


@pytest.mark.asyncio
async def test_write_reasons_caps_model_batch_and_takes_highest_scored():
    """examiner_report.md re-review, Round 1: an unbounded batch (119
    cards on a real google.com scan) reliably timed out and fell back to
    the deterministic template on every single card. The batch must be
    capped at MAX_MODEL_BATCH, and the cards actually sent to the model
    must be the highest-scored ones."""
    total = MAX_MODEL_BATCH + 10
    cards = [_card(f"d{i}.com", score_total=i) for i in range(total)]
    cfg = AnthropicConfig(api_key="fake-key-for-mock-only")

    text_block = MagicMock()
    text_block.type = "text"

    captured_prompts = []

    async def fake_create(**kwargs):
        content = kwargs["messages"][0]["content"]
        captured_prompts.append(content)
        facts = json.loads(content.split("\n", 1)[1])
        text_block.text = json.dumps(
            {"reasons": [{"domain": f["domain"], "reason": "model reason"} for f in facts]}
        )
        resp = MagicMock()
        resp.content = [text_block]
        return resp

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(side_effect=fake_create)

    with patch("anthropic.AsyncAnthropic", return_value=mock_client):
        ok = await write_reasons(cards, cfg)

    assert ok is True
    # A4: MAX_MODEL_BATCH is split into two concurrent MODEL_BATCH_CHUNK_SIZE calls
    assert len(captured_prompts) == MAX_MODEL_BATCH // MODEL_BATCH_CHUNK_SIZE
    sent_domains = set()
    for prompt in captured_prompts:
        facts = json.loads(prompt.split("\n", 1)[1])
        assert len(facts) == MODEL_BATCH_CHUNK_SIZE
        sent_domains.update(f["domain"] for f in facts)
    # the MAX_MODEL_BATCH highest-scored cards (scores total-1 .. total-MAX_MODEL_BATCH)
    expected_domains = {f"d{i}.com" for i in range(total - MAX_MODEL_BATCH, total)}
    assert sent_domains == expected_domains

    # cards beyond the cap still get a reason (deterministic fallback)
    beyond_cap = [c for c in cards if c.domain not in sent_domains and c.band == Band.STRANGERS]
    assert beyond_cap and all(c.reason for c in beyond_cap)
    assert all(c.reason for c in cards)


@pytest.mark.asyncio
async def test_write_reasons_one_chunk_fails_falls_back_only_for_that_chunk(caplog):
    """A4: with two concurrent chunks, one succeeding and one failing,
    only the failing chunk's cards fall back to the deterministic
    template, and exactly one WARNING is logged for the failure."""
    total = MAX_MODEL_BATCH
    cards = [_card(f"d{i}.com", score_total=i) for i in range(total)]
    cfg = AnthropicConfig(api_key="fake-key-for-mock-only")

    # highest-scored chunk (d9..d5, the first MODEL_BATCH_CHUNK_SIZE sent) succeeds;
    # the second chunk (d4..d0) fails.
    failing_domains = {f"d{i}.com" for i in range(total - MODEL_BATCH_CHUNK_SIZE)}

    async def fake_create(**kwargs):
        content = kwargs["messages"][0]["content"]
        facts = json.loads(content.split("\n", 1)[1])
        domains = {f["domain"] for f in facts}
        if domains & failing_domains:
            raise TimeoutError("simulated model timeout")
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = json.dumps(
            {"reasons": [{"domain": f["domain"], "reason": "model reason"} for f in facts]}
        )
        resp = MagicMock()
        resp.content = [text_block]
        return resp

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(side_effect=fake_create)

    with caplog.at_level("WARNING", logger="squatwatch.reason"):
        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            ok = await write_reasons(cards, cfg, brand="example.com")

    assert ok is False
    succeeded = [c for c in cards if c.domain not in failing_domains]
    failed = [c for c in cards if c.domain in failing_domains]
    assert all(c.reason == "model reason" for c in succeeded)
    assert all(c.reason != "model reason" and c.reason for c in failed)

    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "TimeoutError" in message
    assert f"chunk_size={MODEL_BATCH_CHUNK_SIZE}" in message
    assert "brand=example.com" in message
    # never the prompt or the key
    assert "d0.com" not in message
    assert "fake-key" not in message


@pytest.mark.asyncio
async def test_write_reasons_no_cap_needed_for_small_batches():
    cards = [_card(f"d{i}.com", score_total=i) for i in range(3)]
    cfg = AnthropicConfig(api_key="")
    await write_reasons(cards, cfg)
    assert all(c.reason for c in cards)


@pytest.mark.asyncio
async def test_free_band_copy_never_pairs_free_with_a_shown_price():
    """A3 (creative_review.md Round 1): the free-band card template shows
    "$<price>/yr · <reason>" (templates/_macros.html) — pairing a shown
    price with reason text that also says "free" reads as
    self-contradictory. The deterministic FREE-band sentence must not
    contain "free" at all, regardless of whether the card carries a
    price."""
    card = _card("free-example.com", score_total=1, band=Band.FREE)
    cfg = AnthropicConfig(api_key="")
    await write_reasons([card], cfg)
    assert "free" not in card.reason.lower()
    assert "available to register today" in card.reason.lower()


def test_fact_tuple_google_search_is_a_genuine_tri_state():
    """A1 (project_brief.md Section 9c, honesty boundary Section 8): a
    real bool(appears) collapsed "not checked" (cap/quota/no_key/error)
    into the same False as a genuine "does not appear" — the model could
    then narrate "doesn't show up in search" on a card whose search was
    never actually run. The fact tuple must distinguish all three."""
    appears = _card("a.com", 1, search=SearchInfo(checked=True, appears=True))
    absent = _card("b.com", 1, search=SearchInfo(checked=True, appears=False))
    uncapped = _card("c.com", 1, search=SearchInfo(checked=False, reason="cap"))
    errored = _card("d.com", 1, search=SearchInfo(checked=False, reason="error"))

    assert _fact_tuple(appears)["google_search"] == "appears"
    assert _fact_tuple(absent)["google_search"] == "does not appear"
    assert _fact_tuple(uncapped)["google_search"] == "not checked"
    assert _fact_tuple(errored)["google_search"] == "not checked"


def test_deterministic_reason_states_search_not_checked_explicitly():
    """A1: the deterministic fallback -- the guard's replacement target
    -- must itself say "search not checked" for any checked=False card,
    not stay silent about search the way it used to."""
    card = _card("a.com", 1, search=SearchInfo(checked=False, reason="cap"))
    assert "search not checked" in _deterministic_reason(card)


def test_deterministic_reason_omits_search_not_checked_when_actually_checked():
    checked_absent = _card("a.com", 1, search=SearchInfo(checked=True, appears=False))
    checked_present = _card("b.com", 1, search=SearchInfo(checked=True, appears=True))
    assert "search not checked" not in _deterministic_reason(checked_absent)
    assert "found in search" in _deterministic_reason(checked_present)
    assert "search not checked" not in _deterministic_reason(checked_present)


@pytest.mark.asyncio
async def test_guard_replaces_model_reason_that_invents_a_search_claim_on_unchecked_card():
    """A1: the post-call guard -- if the model ignores the system prompt
    and writes a sentence mentioning search/Google/index for a card whose
    search was never checked, that sentence must be replaced with the
    deterministic one, not shipped to the user."""
    card = _card("a.com", 5, search=SearchInfo(checked=False, reason="cap"))
    cfg = AnthropicConfig(api_key="fake-key-for-mock-only")

    async def fake_create(**kwargs):
        return _mock_response({"a.com": "This domain doesn't show up in Google search results."})

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(side_effect=fake_create)

    with patch("anthropic.AsyncAnthropic", return_value=mock_client):
        await write_reasons([card], cfg)

    assert card.reason == _deterministic_reason(card)
    assert "search not checked" in card.reason
    assert "doesn't show up" not in card.reason


@pytest.mark.asyncio
async def test_guard_leaves_model_reason_alone_when_search_was_genuinely_checked():
    """The guard must not fire on a card whose search really was checked
    -- the model is correctly allowed to reference a real search fact."""
    card = _card("a.com", 5, search=SearchInfo(checked=True, appears=True, first_title="Example"))
    cfg = AnthropicConfig(api_key="fake-key-for-mock-only")

    async def fake_create(**kwargs):
        return _mock_response({"a.com": "This domain appears in Google search results."})

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(side_effect=fake_create)

    with patch("anthropic.AsyncAnthropic", return_value=mock_client):
        await write_reasons([card], cfg)

    assert card.reason == "This domain appears in Google search results."


@pytest.mark.asyncio
async def test_guard_leaves_model_reason_alone_when_it_never_mentions_search():
    """The guard is precise: it only replaces sentences that actually
    mention search/Google/index, not every reason on an unchecked card."""
    card = _card("a.com", 5, search=SearchInfo(checked=False, reason="cap"))
    cfg = AnthropicConfig(api_key="fake-key-for-mock-only")

    async def fake_create(**kwargs):
        return _mock_response({"a.com": "A homoglyph variant with mail configured."})

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(side_effect=fake_create)

    with patch("anthropic.AsyncAnthropic", return_value=mock_client):
        await write_reasons([card], cfg)

    assert card.reason == "A homoglyph variant with mail configured."


def test_mentions_search_ignores_innocuous_substrings():
    """Round 4 adversarial re-review (examiner_report.md): plain substring
    matching false-positived on words that merely CONTAIN 'search'/
    'google'/'index' -- fixed with word-boundary matching."""
    assert not _mentions_search("This domain was found after extensive research into your competitors.")
    assert not _mentions_search("The site is hosted near the Googleplex campus in Mountain View.")


def test_mentions_search_catches_a_paraphrase_that_avoids_the_literal_words():
    """Round 4 adversarial re-review: a hallucinated search claim that
    avoids 'search'/'google'/'index' entirely ('doesn't show up when
    people look you up online') must still be caught -- the honesty
    boundary this guard exists for is about the CLAIM, not the vocabulary."""
    assert _mentions_search("This domain does not show up when people look you up online.")


def test_mentions_search_catches_ordinary_verb_inflections():
    """Round 4 second adversarial re-review pass: 'searching'/'searchable'
    are ordinary grammar, not exotic paraphrase -- \\bsearch\\b alone
    missed them entirely."""
    assert _mentions_search("People searching for your brand will land on this page instead.")
    assert _mentions_search("This page is now searchable and ranks for your brand name online.")


@pytest.mark.asyncio
async def test_guard_catches_a_paraphrase_evasion_end_to_end():
    """The widened guard must actually fire inside write_reasons, not just
    in the standalone _mentions_search unit check."""
    card = _card("a.com", 5, search=SearchInfo(checked=False, reason="cap"))
    cfg = AnthropicConfig(api_key="fake-key-for-mock-only")

    async def fake_create(**kwargs):
        return _mock_response(
            {"a.com": "This domain does not show up when people look you up online."}
        )

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(side_effect=fake_create)

    with patch("anthropic.AsyncAnthropic", return_value=mock_client):
        await write_reasons([card], cfg)

    assert card.reason == _deterministic_reason(card)
    assert "search not checked" in card.reason
